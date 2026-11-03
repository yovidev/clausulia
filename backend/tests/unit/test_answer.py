import json
import uuid
from typing import Any

import pytest

from app.core.config import Settings
from app.ingestion.embeddings import FakeEmbedder
from app.llm.base import LLMResult
from app.rag import answer as answer_module
from app.rag.answer import AnswerOutcome, _snippet, answer_question
from app.retrieval.search import RetrievalResult, RetrievedChunk
from app.schemas.ask import AskIn

DOC_A, DOC_B = uuid.uuid4(), uuid.uuid4()


class ScriptedLLM:
    """LLM doble: devuelve en orden los textos programados y guarda lo que recibe."""

    name = "scripted"

    def __init__(self, *texts: str, retries: int = 0) -> None:
        self.texts = list(texts)
        self.retries = retries
        self.prompts: list[str] = []

    def generate(self, system: str, user: str) -> LLMResult:
        self.prompts.append(user)
        return LLMResult(
            text=self.texts.pop(0),
            model="scripted-1",
            tokens_input=100,
            tokens_output=20,
            retries=self.retries,
        )


def _chunk(similarity: float, document_id: uuid.UUID = DOC_A, page: int = 1) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=document_id,
        document_name="a.pdf" if document_id == DOC_A else "b.pdf",
        page_number=page,
        content=f"Contenido de la página {page}.",
        similarity=similarity,
    )


def _llm_json(citations: list[Any], **fields: Any) -> str:
    payload = {
        "answer": "El plazo es de 30 días.",
        "citations": [str(c) for c in citations],
        "confidence": "high",
        "insufficient_evidence": False,
        **fields,
    }
    return json.dumps(payload)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://unused",
        redis_url="redis://unused",
        similarity_threshold=0.35,
        confidence_high_similarity=0.6,
        confidence_medium_similarity=0.45,
    )


@pytest.fixture
def retrieved(monkeypatch: pytest.MonkeyPatch) -> list[RetrievedChunk]:
    """Sustituye search_chunks: los tests deciden qué devuelve la recuperación."""
    chunks: list[RetrievedChunk] = []

    def fake_search(*args: Any, threshold: float, **kwargs: Any) -> RetrievalResult:
        return RetrievalResult(
            chunks=chunks, relevant=[c for c in chunks if c.similarity >= threshold]
        )

    monkeypatch.setattr(answer_module, "search_chunks", fake_search)
    return chunks


def _ask(llm: ScriptedLLM, settings: Settings) -> AnswerOutcome:
    session: Any = None  # sin document_ids no se consulta la base
    return answer_question(
        session, FakeEmbedder(), llm, settings, "org-a", AskIn(question="¿Plazo de pago?")
    )


def test_without_relevant_chunks_llm_is_not_called(
    settings: Settings, retrieved: list[RetrievedChunk]
) -> None:
    retrieved.append(_chunk(0.2))  # por debajo del umbral
    llm = ScriptedLLM()

    outcome = _ask(llm, settings)

    assert outcome.response.status == "insufficient_evidence"
    assert outcome.response.citations == []
    assert llm.prompts == []
    assert outcome.llm_called is False


def test_answered_with_citation_data(settings: Settings, retrieved: list[RetrievedChunk]) -> None:
    chunk = _chunk(0.7, page=4)
    retrieved.append(chunk)

    outcome = _ask(ScriptedLLM(_llm_json([chunk.chunk_id])), settings)

    response = outcome.response
    assert response.status == "answered"
    assert response.answer == "El plazo es de 30 días."
    assert response.confidence == "high"
    [citation] = response.citations
    assert citation.chunk_id == chunk.chunk_id
    assert (citation.document_name, citation.page) == ("a.pdf", 4)
    assert (outcome.tokens_input, outcome.tokens_output, outcome.retries) == (100, 20, 0)


def test_invalid_json_once_then_valid_is_answered_with_one_retry(
    settings: Settings, retrieved: list[RetrievedChunk]
) -> None:
    chunk = _chunk(0.7)
    retrieved.append(chunk)
    llm = ScriptedLLM("no es json", _llm_json([chunk.chunk_id]))

    outcome = _ask(llm, settings)

    assert outcome.response.status == "answered"
    assert outcome.retries == 1
    assert (outcome.tokens_input, outcome.tokens_output) == (200, 40)
    assert "no era JSON válido" in llm.prompts[1]
    assert llm.prompts[1].startswith(llm.prompts[0])


def test_provider_retries_are_added_to_json_retries(
    settings: Settings, retrieved: list[RetrievedChunk]
) -> None:
    chunk = _chunk(0.7)
    retrieved.append(chunk)

    outcome = _ask(ScriptedLLM(_llm_json([chunk.chunk_id]), retries=2), settings)

    assert outcome.retries == 2


def test_invalid_json_twice_is_rejected(
    settings: Settings, retrieved: list[RetrievedChunk]
) -> None:
    retrieved.append(_chunk(0.7))
    llm = ScriptedLLM("no es json", '{"answer": "sin el resto de campos"}')

    outcome = _ask(llm, settings)

    assert outcome.response.status == "rejected"
    assert outcome.response.answer is None
    assert outcome.response.citations == []
    assert len(llm.prompts) == 2


def test_llm_saying_insufficient_evidence_is_respected(
    settings: Settings, retrieved: list[RetrievedChunk]
) -> None:
    retrieved.append(_chunk(0.7))
    llm = ScriptedLLM(_llm_json([], insufficient_evidence=True, confidence="low"))

    assert _ask(llm, settings).response.status == "insufficient_evidence"


def test_invented_citations_are_dropped_and_none_left_means_insufficient(
    settings: Settings, retrieved: list[RetrievedChunk]
) -> None:
    retrieved.append(_chunk(0.7))
    not_retrieved = _chunk(0.9)  # existe, pero no se le pasó al LLM

    outcome = _ask(ScriptedLLM(_llm_json(["inventado", not_retrieved.chunk_id])), settings)

    assert outcome.response.status == "insufficient_evidence"
    assert outcome.response.citations == []


def test_valid_citations_are_kept_deduplicated_and_in_order(
    settings: Settings, retrieved: list[RetrievedChunk]
) -> None:
    first, second = _chunk(0.7, page=1), _chunk(0.6, page=2)
    retrieved.extend([first, second])
    citations = [second.chunk_id, "inventado", second.chunk_id, first.chunk_id]

    outcome = _ask(ScriptedLLM(_llm_json(citations)), settings)

    assert [c.chunk_id for c in outcome.response.citations] == [
        second.chunk_id,
        first.chunk_id,
    ]


@pytest.mark.parametrize(
    ("llm_confidence", "similarity", "expected"),
    [
        ("high", 0.7, "high"),
        ("high", 0.5, "medium"),  # la similitud limita
        ("high", 0.4, "low"),
        ("low", 0.9, "low"),  # el LLM limita
        ("medium", 0.6, "medium"),
    ],
)
def test_confidence_is_minimum_of_llm_and_similarity(
    settings: Settings,
    retrieved: list[RetrievedChunk],
    llm_confidence: str,
    similarity: float,
    expected: str,
) -> None:
    chunk = _chunk(similarity)
    retrieved.append(chunk)

    llm = ScriptedLLM(_llm_json([chunk.chunk_id], confidence=llm_confidence))

    assert _ask(llm, settings).response.confidence == expected


def test_confidence_uses_best_cited_similarity(
    settings: Settings, retrieved: list[RetrievedChunk]
) -> None:
    weak, strong = _chunk(0.4), _chunk(0.65)
    retrieved.extend([strong, weak])

    outcome = _ask(ScriptedLLM(_llm_json([weak.chunk_id, strong.chunk_id])), settings)

    assert outcome.response.confidence == "high"


def test_has_conflict_requires_two_distinct_documents(
    settings: Settings, retrieved: list[RetrievedChunk]
) -> None:
    a1, a2, b1 = _chunk(0.7, DOC_A, 1), _chunk(0.7, DOC_A, 2), _chunk(0.7, DOC_B, 1)
    retrieved.extend([a1, a2, b1])

    same_doc = _ask(ScriptedLLM(_llm_json([a1.chunk_id, a2.chunk_id], has_conflict=True)), settings)
    two_docs = _ask(ScriptedLLM(_llm_json([a1.chunk_id, b1.chunk_id], has_conflict=True)), settings)
    not_said = _ask(ScriptedLLM(_llm_json([a1.chunk_id, b1.chunk_id])), settings)

    assert same_doc.response.has_conflict is False
    assert two_docs.response.has_conflict is True
    assert not_said.response.has_conflict is False


def test_snippet_cuts_at_word_boundary() -> None:
    text = "palabra " * 60  # 480 caracteres

    snippet = _snippet(text)

    assert len(snippet) <= 301
    assert snippet.endswith("palabra…")
    assert _snippet("corto") == "corto"
