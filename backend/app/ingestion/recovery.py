"""Rescate de documentos que quedaron atascados en 'pending' o 'processing'."""

import uuid
from datetime import datetime, timedelta

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import Document, DocumentStatus

log = structlog.get_logger(__name__)


def find_stuck_documents(
    session_factory: sessionmaker[Session], settings: Settings, now: datetime
) -> list[uuid.UUID]:
    """Devuelve los documentos a reencolar y marca como fallidos los que agotaron intentos."""
    cutoff = now - timedelta(minutes=settings.stuck_after_minutes)
    to_requeue: list[uuid.UUID] = []
    with session_factory() as session, session.begin():
        stuck = session.scalars(
            select(Document)
            .where(
                or_(
                    and_(
                        Document.status == DocumentStatus.PROCESSING,
                        Document.processing_started_at < cutoff,
                    ),
                    and_(
                        Document.status == DocumentStatus.PENDING,
                        Document.updated_at < cutoff,
                    ),
                )
            )
            .with_for_update(skip_locked=True)
        ).all()
        for document in stuck:
            if document.attempts >= settings.max_ingest_attempts:
                document.status = DocumentStatus.FAILED
                document.error_code = "STUCK"
                document.error_message = "El procesamiento no terminó tras varios intentos"
                document.processing_started_at = None
                log.warning("document_stuck_failed", document_id=str(document.id))
            else:
                # Se renueva la marca de tiempo para no reencolarlo en cada barrido.
                document.processing_started_at = now
                document.updated_at = now
                to_requeue.append(document.id)
                log.info("document_stuck_requeued", document_id=str(document.id))
    return to_requeue
