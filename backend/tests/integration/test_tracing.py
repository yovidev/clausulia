"""Spans manuales de la ingesta y de la pregunta, capturados en memoria."""

import hashlib
import uuid
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import Document
from app.ingestion.embeddings import FakeEmbedder
from app.ingestion.extraction import PypdfExtractor
from app.ingestion.service import run_ingestion
from app.llm.base import LLMTimeoutError
from app.llm.mock import MockProvider
from app.rag.answer import answer_question
from app.schemas.ask import AskIn
from tests.factories import make_pdf

pytestmark = pytest.mark.integration

PAGES = [
    "El plazo de pago de las facturas es de treinta dias naturales.",
    "La penalizacion por retraso en la entrega es del dos por ciento semanal.",
]
QUESTION = AskIn(question="Cual es la penalizacion por retraso en la entrega?")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://unused",
        redis_url="redis://unused",
        upload_dir=str(tmp_path),
        embedding_provider="fake",
        similarity_threshold=0.3,
    )


def _create_document(session_factory: sessionmaker[Session], settings: Settings) -> uuid.UUID:
    pdf = make_pdf(Path(settings.upload_dir) / "tmp.pdf", PAGES)
    data = pdf.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    pdf.replace(Path(settings.upload_dir) / f"{sha256}.pdf")
    with session_factory() as session, session.begin():
        document = Document(
            organization_id="org-a", filename="contrato.pdf", sha256=sha256, size_bytes=len(data)
        )
        session.add(document)
        session.flush()
        return document.id


def _ingest(
    document_id: uuid.UUID, session_factory: sessionmaker[Session], settings: Settings
) -> None:
    run_ingestion(
        document_id,
        session_factory=session_factory,
        extractor=PypdfExtractor(),
        embedder=FakeEmbedder(),
        settings=settings,
    )


def _by_name(exporter: InMemorySpanExporter) -> dict[str, ReadableSpan]:
    return {span.name: span for span in exporter.get_finished_spans()}


def _attrs(span: ReadableSpan) -> dict[str, object]:
    return dict(span.attributes or {})


def test_ingestion_produces_spans_with_attributes(
    session_factory: sessionmaker[Session],
    settings: Settings,
    span_exporter: InMemorySpanExporter,
) -> None:
    document_id = _create_document(session_factory, settings)

    _ingest(document_id, session_factory, settings)

    spans = _by_name(span_exporter)
    root = spans["ingest.document"]
    assert _attrs(root)["document.id"] == str(document_id)
    assert _attrs(root)["organization.id"] == "org-a"
    assert _attrs(root)["ingest.attempt"] == 1
    assert _attrs(root)["ingest.status"] == "ready"
    assert isinstance(_attrs(root)["ingest.duration_ms"], float)
    assert _attrs(spans["pdf.extract"])["pdf.pages"] == 2
    assert _attrs(spans["chunking"])["chunks.count"] == 2
    assert _attrs(spans["embeddings"]) == {"embeddings.count": 2, "embeddings.model": "fake"}
    assert _attrs(spans["db.write_chunks"])["chunks.count"] == 2
    for name in ("pdf.extract", "chunking", "embeddings", "db.write_chunks"):
        assert spans[name].parent is not None
        assert root.context is not None
        assert spans[name].parent.span_id == root.context.span_id


def test_failed_ingestion_marks_span_as_error(
    session_factory: sessionmaker[Session],
    settings: Settings,
    span_exporter: InMemorySpanExporter,
) -> None:
    document_id = _create_document(session_factory, settings)
    next(Path(settings.upload_dir).glob("*.pdf")).write_bytes(b"%PDF-roto")

    _ingest(document_id, session_factory, settings)

    spans = _by_name(span_exporter)
    assert spans["ingest.document"].status.status_code == StatusCode.ERROR
    assert _attrs(spans["ingest.document"])["error.code"] == "INVALID_PDF"
    assert spans["pdf.extract"].status.status_code == StatusCode.ERROR
    assert [e.name for e in spans["pdf.extract"].events] == ["exception"]


def test_answer_question_produces_expected_spans(
    session_factory: sessionmaker[Session],
    settings: Settings,
    span_exporter: InMemorySpanExporter,
) -> None:
    _ingest(_create_document(session_factory, settings), session_factory, settings)
    span_exporter.clear()

    with session_factory() as session:
        outcome = answer_question(
            session, FakeEmbedder(), MockProvider(), settings, "org-a", QUESTION
        )

    assert outcome.response.status == "answered"
    spans = _by_name(span_exporter)
    expected = {"ask", "embed_query", "pgvector.search", "llm.generate", "validate_answer"}
    assert set(spans) == expected

    ask = _attrs(spans["ask"])
    assert ask["organization.id"] == "org-a"
    assert ask["ask.status"] == "answered"
    assert isinstance(ask["ask.duration_ms"], float)

    search = _attrs(spans["pgvector.search"])
    assert search["search.k"] == settings.retrieval_k
    assert search["search.threshold"] == 0.3
    assert search["chunks.retrieved"] == 2
    assert search["search.mode"] == settings.retrieval_mode
    assert search["evidence.sufficient"] is True
    assert search["similarity.top"] == max(outcome.similarities)

    llm = _attrs(spans["llm.generate"])
    assert llm["llm.provider"] == "mock"
    assert llm["llm.model"] == "mock-1"
    assert llm["llm.tokens.input"] == outcome.tokens_input > 0
    assert llm["llm.tokens.output"] == outcome.tokens_output > 0
    assert llm["llm.retries"] == 0
    assert isinstance(llm["llm.generate.duration_ms"], float)

    assert _attrs(spans["validate_answer"]) == {"citations.valid": 1, "citations.discarded": 0}

    root = spans["ask"]
    assert root.context is not None
    for name in ("embed_query", "pgvector.search", "llm.generate", "validate_answer"):
        parent = spans[name].parent
        assert parent is not None and parent.span_id == root.context.span_id


def test_llm_error_is_recorded_on_spans(
    session_factory: sessionmaker[Session],
    settings: Settings,
    span_exporter: InMemorySpanExporter,
) -> None:
    _ingest(_create_document(session_factory, settings), session_factory, settings)
    span_exporter.clear()

    with session_factory() as session, pytest.raises(LLMTimeoutError):
        answer_question(
            session, FakeEmbedder(), MockProvider("timeout"), settings, "org-a", QUESTION
        )

    spans = _by_name(span_exporter)
    for name in ("llm.generate", "ask"):
        assert spans[name].status.status_code == StatusCode.ERROR
        assert "exception" in [e.name for e in spans[name].events]
