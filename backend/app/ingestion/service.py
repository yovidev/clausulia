"""Ingesta de un documento: extraer, trocear, vectorizar y guardar de forma atómica."""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath

import structlog
from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode
from opentelemetry.util.types import AttributeValue
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.telemetry import timed_span
from app.db.models import Chunk, Document, DocumentStatus
from app.ingestion.chunking import chunk_pages
from app.ingestion.embeddings import Embedder
from app.ingestion.extraction import PdfExtractionError, PdfExtractor
from app.ingestion.storage import upload_path

log = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


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
    with timed_span(
        tracer,
        "ingest.document",
        {"document.id": str(document_id)},
        duration_attribute="ingest.duration_ms",
    ) as span:
        status = _ingest(span, document_id, session_factory, extractor, embedder, settings)
        span.set_attribute("ingest.status", status.value if status else "skipped")
        return status


def _ingest(
    span: Span,
    document_id: uuid.UUID,
    session_factory: sessionmaker[Session],
    extractor: PdfExtractor,
    embedder: Embedder,
    settings: Settings,
) -> DocumentStatus | None:
    claim = _claim(session_factory, document_id)
    if claim is None:
        return None
    span.set_attribute("organization.id", claim.organization_id)
    span.set_attribute("ingest.attempt", claim.attempt)

    try:
        with tracer.start_as_current_span("pdf.extract") as extract_span:
            pages = extractor.extract(
                upload_path(settings.upload_dir, claim.sha256), settings.max_pages
            )
            extract_span.set_attribute("pdf.pages", len(pages))
    except PdfExtractionError as exc:
        return _fail(span, session_factory, document_id, exc.code, exc.message)
    except FileNotFoundError:
        return _fail(
            span, session_factory, document_id, "FILE_MISSING", "El archivo subido no se encuentra"
        )

    with tracer.start_as_current_span("chunking") as chunking_span:
        chunks = chunk_pages(pages, settings.chunk_size, settings.chunk_overlap)
        chunking_span.set_attribute("chunks.count", len(chunks))
    if not chunks:
        return _fail(span, session_factory, document_id, "NO_TEXT_LAYER", "El PDF no tiene texto")

    embed_attributes: dict[str, AttributeValue] = {
        "embeddings.count": len(chunks),
        "embeddings.model": embedder.name,
    }
    with tracer.start_as_current_span("embeddings", attributes=embed_attributes):
        title = document_title(claim.filename) if settings.embed_document_title else None
        vectors = embedder.embed_documents([embedding_text(c.content, title) for c in chunks])

    with (
        tracer.start_as_current_span("db.write_chunks", attributes={"chunks.count": len(chunks)}),
        session_factory() as session,
        session.begin(),
    ):
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


@dataclass(frozen=True)
class _Claim:
    sha256: str
    filename: str
    organization_id: str
    attempt: int


def document_title(filename: str) -> str:
    """Nombre legible para la cabecera: sin extensión y con _ y - como espacios."""
    return re.sub(r"[_-]+", " ", PurePath(filename).stem).strip()


def embedding_text(content: str, title: str | None) -> str:
    """Texto que se vectoriza. El content guardado y mostrado no cambia.

    Con título (contextual chunk header), el vector sabe de qué documento es el chunk:
    "el contrato con Peñalara" puede acercarse a una cláusula que no nombra al proveedor.
    """
    return f"Documento: {title}\n{content}" if title else content


def _claim(session_factory: sessionmaker[Session], document_id: uuid.UUID) -> _Claim | None:
    """Marca el documento como en proceso. Devuelve lo necesario para procesarlo, o None."""
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
        return _Claim(
            document.sha256, document.filename, document.organization_id, document.attempts
        )


def _fail(
    span: Span,
    session_factory: sessionmaker[Session],
    document_id: uuid.UUID,
    code: str,
    message: str,
) -> DocumentStatus:
    """Fallo permanente: se marca el documento y el span queda en ERROR con el código."""
    span.set_status(Status(StatusCode.ERROR, code))
    span.set_attribute("error.code", code)
    mark_failed(session_factory, document_id, code, message)
    return DocumentStatus.FAILED


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
