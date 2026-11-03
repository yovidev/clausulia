import hashlib
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import EMBEDDING_DIM, Chunk, Document, DocumentStatus
from app.ingestion.embeddings import FakeEmbedder
from app.ingestion.extraction import PypdfExtractor
from app.ingestion.service import run_ingestion
from tests.factories import make_pdf

pytestmark = pytest.mark.integration

CONTRACT_PAGES = [
    "El contrato se renueva automaticamente cada doce meses salvo preaviso.",
    "La penalizacion por retraso en la entrega sera del dos por ciento semanal.",
]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://unused",
        redis_url="redis://unused",
        upload_dir=str(tmp_path),
        chunk_size=300,
        chunk_overlap=50,
        embedding_provider="fake",
    )


def _create_document(
    session_factory: sessionmaker[Session], settings: Settings, pages: list[str] | None
) -> uuid.UUID:
    """Crea la fila del documento y, si `pages` no es None, el PDF en el almacenamiento."""
    pdf = make_pdf(Path(settings.upload_dir) / "source.pdf", pages or ["placeholder"])
    data = pdf.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    if pages is not None:
        pdf.rename(Path(settings.upload_dir) / f"{sha256}.pdf")
    with session_factory() as session, session.begin():
        document = Document(
            organization_id="org-a", filename="contrato.pdf", sha256=sha256, size_bytes=len(data)
        )
        session.add(document)
        session.flush()
        return document.id


def _ingest(
    document_id: uuid.UUID,
    session_factory: sessionmaker[Session],
    settings: Settings,
    embedder: object | None = None,
) -> DocumentStatus | None:
    return run_ingestion(
        document_id,
        session_factory=session_factory,
        extractor=PypdfExtractor(),
        embedder=embedder or FakeEmbedder(),  # type: ignore[arg-type]
        settings=settings,
    )


def _chunk_count(session_factory: sessionmaker[Session], document_id: uuid.UUID) -> int:
    with session_factory() as session:
        return (
            session.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
            )
            or 0
        )


def test_ingestion_stores_chunks_with_pages(
    session_factory: sessionmaker[Session], settings: Settings
) -> None:
    document_id = _create_document(session_factory, settings, CONTRACT_PAGES)

    assert _ingest(document_id, session_factory, settings) == DocumentStatus.READY

    with session_factory() as session:
        document = session.get_one(Document, document_id)
        chunks = session.scalars(select(Chunk).where(Chunk.document_id == document_id)).all()
    assert document.status == DocumentStatus.READY
    assert document.page_count == 2
    assert document.chunk_count == len(chunks)
    assert {c.page_number for c in chunks} == {1, 2}
    assert all(len(c.embedding) == EMBEDDING_DIM for c in chunks)


def test_running_twice_does_not_duplicate_chunks(
    session_factory: sessionmaker[Session], settings: Settings
) -> None:
    document_id = _create_document(session_factory, settings, CONTRACT_PAGES)
    _ingest(document_id, session_factory, settings)
    first_count = _chunk_count(session_factory, document_id)

    assert _ingest(document_id, session_factory, settings) is None  # ya estaba listo
    assert _chunk_count(session_factory, document_id) == first_count


def test_redelivery_after_crash_replaces_stale_chunks(
    session_factory: sessionmaker[Session], settings: Settings
) -> None:
    """Simula un worker que murió dejando el documento en 'processing' con chunks viejos."""
    document_id = _create_document(session_factory, settings, CONTRACT_PAGES)
    with session_factory() as session, session.begin():
        document = session.get_one(Document, document_id)
        document.status = DocumentStatus.PROCESSING
        session.add(
            Chunk(
                document_id=document_id,
                chunk_index=0,
                page_number=1,
                content="chunk viejo",
                embedding=[0.1] * EMBEDDING_DIM,
            )
        )

    assert _ingest(document_id, session_factory, settings) == DocumentStatus.READY

    with session_factory() as session:
        contents = session.scalars(
            select(Chunk.content).where(Chunk.document_id == document_id)
        ).all()
        document = session.get_one(Document, document_id)
    assert "chunk viejo" not in contents
    assert document.chunk_count == len(contents)


def test_scanned_pdf_is_marked_failed(
    session_factory: sessionmaker[Session], settings: Settings
) -> None:
    document_id = _create_document(session_factory, settings, ["", ""])

    assert _ingest(document_id, session_factory, settings) == DocumentStatus.FAILED

    with session_factory() as session:
        document = session.get_one(Document, document_id)
    assert document.error_code == "NO_TEXT_LAYER"
    assert _chunk_count(session_factory, document_id) == 0


def test_missing_file_is_marked_failed(
    session_factory: sessionmaker[Session], settings: Settings
) -> None:
    document_id = _create_document(session_factory, settings, None)

    assert _ingest(document_id, session_factory, settings) == DocumentStatus.FAILED

    with session_factory() as session:
        assert session.get_one(Document, document_id).error_code == "FILE_MISSING"


class _BrokenEmbedder:
    name = "broken"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise ConnectionError("el modelo no responde")

    def embed_query(self, text: str) -> list[float]:
        raise ConnectionError("el modelo no responde")


def test_transient_failure_leaves_no_partial_chunks(
    session_factory: sessionmaker[Session], settings: Settings
) -> None:
    document_id = _create_document(session_factory, settings, CONTRACT_PAGES)

    with pytest.raises(ConnectionError):
        _ingest(document_id, session_factory, settings, embedder=_BrokenEmbedder())

    with session_factory() as session:
        document = session.get_one(Document, document_id)
    # Queda en 'processing' para que Celery lo reintente, y sin chunks a medias.
    assert document.status == DocumentStatus.PROCESSING
    assert _chunk_count(session_factory, document_id) == 0


class RecordingEmbedder(FakeEmbedder):
    """FakeEmbedder que guarda los textos que recibe para vectorizar."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return super().embed_documents(texts)


@pytest.mark.parametrize("enabled", [True, False])
def test_document_title_header_is_embedded_but_not_stored(
    session_factory: sessionmaker[Session], settings: Settings, enabled: bool
) -> None:
    document_id = _create_document(session_factory, settings, CONTRACT_PAGES)
    with session_factory() as session, session.begin():
        session.get_one(Document, document_id).filename = "contrato_transporte-penalara.pdf"
    embedder = RecordingEmbedder()

    _ingest(
        document_id,
        session_factory,
        settings.model_copy(update={"embed_document_title": enabled}),
        embedder,
    )

    with session_factory() as session:
        query = select(Chunk.content).where(Chunk.document_id == document_id)
        contents = session.scalars(query.order_by(Chunk.chunk_index)).all()
    header = "Documento: contrato transporte penalara\n"
    expected = [header + c for c in contents] if enabled else list(contents)
    assert embedder.texts == expected
    # El content guardado (el que se muestra y se cita) no lleva la cabecera.
    assert not any(c.startswith("Documento:") for c in contents)
