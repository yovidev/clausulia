import random
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.ingestion.embeddings import get_embedder
from app.ingestion.extraction import PypdfExtractor
from app.ingestion.recovery import find_stuck_documents
from app.ingestion.service import mark_failed, run_ingestion
from app.worker.celery_app import celery_app

log = structlog.get_logger(__name__)

# Errores que pueden resolverse solos: vale la pena reintentar.
TRANSIENT_ERRORS = (OperationalError, ConnectionError, TimeoutError)
MAX_RETRIES = 5


def retry_delay(retries: int) -> float:
    """Backoff exponencial (1, 2, 4… hasta 60 s) más jitter de hasta 1 s."""
    return min(2.0**retries, 60.0) + random.uniform(0, 1)  # noqa: S311  jitter, no criptografía


@celery_app.task(bind=True, name="ingest_document", max_retries=MAX_RETRIES)
def ingest_document(self: Any, document_id: str) -> str | None:
    try:
        status = run_ingestion(
            uuid.UUID(document_id),
            session_factory=get_session_factory(),
            extractor=PypdfExtractor(),
            embedder=get_embedder(),
            settings=get_settings(),
        )
    except TRANSIENT_ERRORS as exc:
        if self.request.retries >= self.max_retries:
            _mark_failed_safely(document_id)
            raise
        delay = retry_delay(self.request.retries)
        log.warning(
            "ingestion_retry", document_id=document_id, retry=self.request.retries, delay=delay
        )
        raise self.retry(exc=exc, countdown=delay) from exc
    return status.value if status else None


@celery_app.task(name="recover_stuck_documents")
def recover_stuck_documents() -> int:
    document_ids = find_stuck_documents(get_session_factory(), get_settings(), datetime.now(UTC))
    for document_id in document_ids:
        ingest_document.delay(str(document_id))
    return len(document_ids)


def enqueue_ingestion(document_id: uuid.UUID) -> None:
    """Punto único para encolar desde la API."""
    ingest_document.delay(str(document_id))


def _mark_failed_safely(document_id: str) -> None:
    try:
        mark_failed(
            get_session_factory(),
            uuid.UUID(document_id),
            "INGESTION_FAILED",
            "El procesamiento falló tras varios reintentos",
        )
    except OperationalError:
        # Si la base sigue caída, el barrido lo marcará como fallido más tarde.
        log.error("could_not_mark_failed", document_id=document_id)
