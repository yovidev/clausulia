"""Orquestación de una pregunta: recuperar, preguntar al LLM, validar y citar."""

import uuid
from dataclasses import dataclass, field

import structlog
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Document, DocumentStatus
from app.ingestion.embeddings import Embedder
from app.llm.base import LLMProvider
from app.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from app.rag.errors import DocumentNotFoundError, DocumentNotReadyError
from app.retrieval.search import RetrievedChunk, search_chunks
from app.schemas.ask import AskIn, AskOut, CitationOut, Confidence, LLMAnswer

log = structlog.get_logger(__name__)

SNIPPET_CHARS = 300
NO_EVIDENCE = "No hay evidencia suficiente en los documentos para responder la pregunta."
_RANK: dict[Confidence, int] = {"low": 0, "medium": 1, "high": 2}


@dataclass
class AnswerOutcome:
    """Respuesta de la API más los datos que irán a las trazas."""

    response: AskOut
    llm_called: bool = False
    tokens_input: int = 0
    tokens_output: int = 0
    retries: int = 0  # reintentos por JSON inválido + reintentos internos del proveedor
    similarities: list[float] = field(default_factory=list)


def answer_question(
    session: Session,
    embedder: Embedder,
    llm: LLMProvider,
    settings: Settings,
    organization_id: str,
    ask: AskIn,
) -> AnswerOutcome:
    if ask.document_ids is not None:
        _check_documents(session, organization_id, ask.document_ids)

    retrieval = search_chunks(
        session,
        embedder,
        ask.question,
        organization_id,
        k=settings.retrieval_k,
        threshold=settings.similarity_threshold,
        document_ids=ask.document_ids,
    )
    outcome = AnswerOutcome(
        response=_insufficient(), similarities=[c.similarity for c in retrieval.chunks]
    )
    if not retrieval.relevant:
        return outcome  # sin evidencia no se llama al LLM

    answer = _ask_llm(llm, build_user_prompt(ask.question, retrieval.relevant), outcome)
    if answer is None:
        outcome.response = AskOut(
            status="rejected", answer=None, citations=[], confidence=None, has_conflict=False
        )
        return outcome
    if answer.insufficient_evidence:
        return outcome

    by_id = {str(c.chunk_id): c for c in retrieval.relevant}
    cited = [by_id[i] for i in dict.fromkeys(answer.citations) if i in by_id]
    if len(cited) < len(answer.citations):
        log.warning("llm_invalid_citations_dropped", dropped=len(answer.citations) - len(cited))
    if not cited:
        return outcome

    # Confianza final: la menor entre la que declara el LLM y la que justifica la similitud.
    by_similarity = _similarity_confidence(max(c.similarity for c in cited), settings)
    outcome.response = AskOut(
        status="answered",
        answer=answer.answer,
        citations=[_citation(c) for c in cited],
        confidence=min(answer.confidence, by_similarity, key=_RANK.__getitem__),
        has_conflict=answer.has_conflict and len({c.document_id for c in cited}) >= 2,
    )
    return outcome


def _check_documents(session: Session, organization_id: str, document_ids: list[uuid.UUID]) -> None:
    rows = session.execute(
        select(Document.id, Document.status).where(
            Document.id.in_(document_ids), Document.organization_id == organization_id
        )
    ).all()
    found = {document_id: status for document_id, status in rows}
    # Los de otra organización se tratan igual que los inexistentes: no se revela que existen.
    missing = [i for i in dict.fromkeys(document_ids) if i not in found]
    if missing:
        raise DocumentNotFoundError(missing)
    not_ready = [i for i, status in found.items() if status != DocumentStatus.READY]
    if not_ready:
        raise DocumentNotReadyError(not_ready)


def _ask_llm(llm: LLMProvider, user: str, outcome: AnswerOutcome) -> LLMAnswer | None:
    """Llama al LLM y valida su JSON. Un solo reintento con el error; None si vuelve a fallar."""
    prompt = user
    for attempt in range(2):
        result = llm.generate(SYSTEM_PROMPT, prompt)
        outcome.llm_called = True
        outcome.tokens_input += result.tokens_input
        outcome.tokens_output += result.tokens_output
        outcome.retries += result.retries + attempt
        try:
            return LLMAnswer.model_validate_json(result.text)
        except ValidationError as exc:
            log.warning("llm_invalid_json", attempt=attempt + 1, errors=exc.error_count())
            prompt = (
                f"{user}\n\nTu respuesta anterior no era JSON válido según el esquema "
                f"({_summarize(exc)}). Responde solo con el objeto JSON del esquema."
            )
    return None


def _summarize(exc: ValidationError) -> str:
    parts = [
        f"{'.'.join(str(p) for p in e['loc']) or 'raíz'}: {e['msg']}" for e in exc.errors()[:3]
    ]
    return "; ".join(parts)[:300]


def _similarity_confidence(similarity: float, settings: Settings) -> Confidence:
    if similarity >= settings.confidence_high_similarity:
        return "high"
    if similarity >= settings.confidence_medium_similarity:
        return "medium"
    return "low"


def _citation(chunk: RetrievedChunk) -> CitationOut:
    return CitationOut(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        document_name=chunk.document_name,
        page=chunk.page_number,
        snippet=_snippet(chunk.content),
    )


def _snippet(text: str) -> str:
    """Recorta a SNIPPET_CHARS sin partir palabras."""
    if len(text) <= SNIPPET_CHARS:
        return text
    cut = text[:SNIPPET_CHARS]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip() + "…"


def _insufficient() -> AskOut:
    return AskOut(
        status="insufficient_evidence",
        answer=NO_EVIDENCE,
        citations=[],
        confidence=None,
        has_conflict=False,
    )
