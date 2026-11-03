"""POST /ask: pregunta en lenguaje natural con respuesta citada."""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_org_id
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.ingestion.embeddings import Embedder, get_embedder
from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider
from app.rag.answer import answer_question
from app.schemas.ask import AskIn, AskOut
from app.schemas.documents import ErrorOut

log = structlog.get_logger(__name__)
router = APIRouter(tags=["ask"])


@router.post(
    "/ask",
    response_model=AskOut,
    responses={code: {"model": ErrorOut} for code in (404, 409, 422, 429, 502, 503, 504)},
)
def ask(
    body: AskIn,
    session: Annotated[Session, Depends(get_db)],
    org_id: Annotated[str, Depends(get_org_id)],
    settings: Annotated[Settings, Depends(get_settings)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
    llm: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> AskOut:
    outcome = answer_question(session, embedder, llm, settings, org_id, body)
    log.info(
        "question_answered",
        status=outcome.response.status,
        llm_called=outcome.llm_called,
        tokens_input=outcome.tokens_input,
        tokens_output=outcome.tokens_output,
        retries=outcome.retries,
    )
    return outcome.response
