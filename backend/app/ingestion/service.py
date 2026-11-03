"""Ingesta de un documento: extraer, trocear, vectorizar y guardar de forma atómica."""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import Chunk, Document, DocumentStatus
from app.ingestion.chunking import chunk_pages
from app.ingestion.embeddings import Embedder
from app.ingestion.extraction import PdfExtractionError, PdfExtractor
from app.ingestion.storage import upload_path

log = structlog.get_logger(__name__)


def run_ingestion(
    document_id: uuid.UUID,
    *,
    session_factory: sessionmaker[Session],
    extractor: PdfExtractor,
    embedder: Embedder,
    settings: Settings,
) -> DocumentStatus | None:
    """Procesa un documento. Devuelve el estado final, o None si no había nada que hacer.

    Los errores transitorios (base de datos, red) se propagan para que Celery reintente.
    Los errores permanentes (PDF inválido) marcan el documento como fallido.
    """
    sha256 = _claim(session_factory, document_id)
    if sha256 is None:
        return None

    try:
        pages = extractor.extract(upload_path(settings.upload_dir, sha256), settings.max_pages)
    except PdfExtractionError as exc:
        mark_failed(session_factory, document_id, exc.code, exc.message)
        return DocumentStatus.FAILED
    except FileNotFoundError:
        mark_failed(
            session_factory, document_id, "FILE_MISSING", "El archivo subido no se encuentra"
        )
        return DocumentStatus.FAILED

    chunks = chunk_pages(pages, settings.chunk_size, settings.chunk_overlap)
    if not chunks:
        mark_failed(session_factory, document_id, "NO_TEXT_LAYER", "El PDF no tiene texto")
        return DocumentStatus.FAILED

    vectors = embedder.embed_documents([c.content for c in chunks])

    with session_factory() as session, session.begin():
        document = session.get(Document, document_id, with_for_update=True)
        if document is None:
            return None
        session.execute(delete(Chunk).where(Chunk.document_id == document_id))
        session.execute(
            insert(Chunk),
            [
                {
                    "id": uuid.uuid4(),
                    "document_id": document_id,
                    "chunk_index": chunk.chunk_index,
                    "page_number": chunk.page_number,
                    "content": chunk.content,
                    "embedding": vector,
                }
                for chunk, vector in zip(chunks, vectors, strict=True)
            ],
        )
        document.status = DocumentStatus.READY
        document.page_count = len(pages)
        document.chunk_count = len(chunks)
        document.processing_started_at = None

    log.info("ingestion_ready", document_id=str(document_id), chunks=len(chunks))
    return DocumentStatus.READY


def _claim(session_factory: sessionmaker[Session], document_id: uuid.UUID) -> str | None:
    """Marca el documento como en proceso. Devuelve su hash, o None si no hay que procesarlo."""
    with session_factory() as session, session.begin():
        document = session.get(Document, document_id, with_for_update=True)
        if document is None:
            log.warning("ingestion_document_not_found", document_id=str(document_id))
            return None
        if document.status == DocumentStatus.READY:
            log.info("ingestion_already_ready", document_id=str(document_id))
            return None
        document.status = DocumentStatus.PROCESSING
        document.attempts += 1
        document.processing_started_at = datetime.now(UTC)
        document.error_code = None
        document.error_message = None
        return document.sha256


def mark_failed(
    session_factory: sessionmaker[Session], document_id: uuid.UUID, code: str, message: str
) -> None:
    with session_factory() as session, session.begin():
        document = session.get(Document, document_id, with_for_update=True)
        if document is None:
            return
        document.status = DocumentStatus.FAILED
        document.error_code = code
        document.error_message = message
        document.processing_started_at = None
    log.warning("ingestion_failed", document_id=str(document_id), code=code)
