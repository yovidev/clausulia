import hashlib
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import Document, DocumentStatus
from app.ingestion.embeddings import FakeEmbedder
from app.ingestion.extraction import PypdfExtractor
from app.ingestion.service import run_ingestion
from app.retrieval.search import search_chunks
from tests.factories import make_pdf

pytestmark = pytest.mark.integration

# Con chunk_size=1000 cada página cabe en un solo chunk.
CONTRACT_PAGES = [
    "El contrato se renueva automaticamente cada doce meses salvo preaviso escrito.",
    "La penalizacion por retraso en la entrega sera del dos por ciento semanal.",
    "Las partes mantendran la confidencialidad de la informacion durante cinco anos.",
]
OTHER_PAGES = ["El proveedor factura mensualmente y el pago vence a los treinta dias."]

QUESTION = "Cual es la penalizacion por retraso en la entrega?"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://unused",
        redis_url="redis://unused",
        upload_dir=str(tmp_path),
        embedding_provider="fake",
    )


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


def _ingest(
    session_factory: sessionmaker[Session],
    settings: Settings,
    pages: list[str],
    org: str = "org-a",
    filename: str = "contrato.pdf",
) -> uuid.UUID:
    """Guarda el PDF, crea el documento y lo ingiere de verdad (con FakeEmbedder)."""
    tmp = make_pdf(Path(settings.upload_dir) / f"{uuid.uuid4().hex}.tmp", pages)
    data = tmp.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    tmp.replace(Path(settings.upload_dir) / f"{sha256}.pdf")
    with session_factory() as session, session.begin():
        document = Document(
            organization_id=org, filename=filename, sha256=sha256, size_bytes=len(data)
        )
        session.add(document)
        session.flush()
        document_id = document.id
    status = run_ingestion(
        document_id,
        session_factory=session_factory,
        extractor=PypdfExtractor(),
        embedder=FakeEmbedder(),
        settings=settings,
    )
    assert status == DocumentStatus.READY
    return document_id


def test_returns_expected_chunk_first_with_citation_data(
    session_factory: sessionmaker[Session], settings: Settings, embedder: FakeEmbedder
) -> None:
    document_id = _ingest(session_factory, settings, CONTRACT_PAGES)

    with session_factory() as session:
        result = search_chunks(session, embedder, QUESTION, "org-a", k=3, threshold=0.2)

    top = result.chunks[0]
    assert top.document_id == document_id
    assert top.document_name == "contrato.pdf"
    assert top.page_number == 2
    assert "penalizacion" in top.content
    assert top in result.relevant
    similarities = [c.similarity for c in result.chunks]
    assert similarities == sorted(similarities, reverse=True)
    assert all(round(s, 4) == s for s in similarities)


def test_respects_k(
    session_factory: sessionmaker[Session], settings: Settings, embedder: FakeEmbedder
) -> None:
    _ingest(session_factory, settings, CONTRACT_PAGES)

    with session_factory() as session:
        result = search_chunks(session, embedder, QUESTION, "org-a", k=2, threshold=0.0)

    assert len(result.chunks) == 2


def test_never_returns_chunks_from_other_org_even_if_identical(
    session_factory: sessionmaker[Session], settings: Settings, embedder: FakeEmbedder
) -> None:
    own = _ingest(session_factory, settings, CONTRACT_PAGES, org="org-a")
    _ingest(session_factory, settings, CONTRACT_PAGES, org="org-b")

    with session_factory() as session:
        result = search_chunks(session, embedder, QUESTION, "org-a", k=10, threshold=0.0)

    assert len(result.chunks) == len(CONTRACT_PAGES)
    assert {c.document_id for c in result.chunks} == {own}


def test_ignores_documents_that_are_not_ready(
    session_factory: sessionmaker[Session], settings: Settings, embedder: FakeEmbedder
) -> None:
    ready = _ingest(session_factory, settings, OTHER_PAGES)
    reprocessing = _ingest(session_factory, settings, CONTRACT_PAGES)
    # Tiene chunks de una ingesta anterior, pero ya no está listo.
    with session_factory() as session, session.begin():
        session.get_one(Document, reprocessing).status = DocumentStatus.PROCESSING

    with session_factory() as session:
        result = search_chunks(session, embedder, QUESTION, "org-a", k=10, threshold=0.0)

    assert {c.document_id for c in result.chunks} == {ready}


def test_filters_by_document_ids(
    session_factory: sessionmaker[Session], settings: Settings, embedder: FakeEmbedder
) -> None:
    _ingest(session_factory, settings, CONTRACT_PAGES)
    other = _ingest(session_factory, settings, OTHER_PAGES, filename="factura.pdf")

    with session_factory() as session:
        result = search_chunks(
            session, embedder, QUESTION, "org-a", k=10, threshold=0.0, document_ids=[other]
        )

    assert [c.document_id for c in result.chunks] == [other]


def test_high_threshold_leaves_relevant_empty_but_keeps_all_chunks(
    session_factory: sessionmaker[Session], settings: Settings, embedder: FakeEmbedder
) -> None:
    _ingest(session_factory, settings, CONTRACT_PAGES)

    with session_factory() as session:
        result = search_chunks(session, embedder, QUESTION, "org-a", k=3, threshold=0.99)

    assert len(result.chunks) == 3
    assert result.relevant == []


def test_iterative_scan_applies_only_to_the_current_transaction(
    session_factory: sessionmaker[Session], settings: Settings, embedder: FakeEmbedder
) -> None:
    _ingest(session_factory, settings, CONTRACT_PAGES)

    with session_factory() as session:
        search_chunks(session, embedder, QUESTION, "org-a", k=3, threshold=0.0)
        inside = session.execute(text("SHOW hnsw.iterative_scan")).scalar_one()
        session.commit()
        # Misma conexión, transacción nueva: SET LOCAL ya no rige.
        after = session.execute(text("SHOW hnsw.iterative_scan")).scalar_one()

    assert inside == "strict_order"
    assert after == "off"
