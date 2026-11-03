import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import Document, DocumentStatus
from app.ingestion.recovery import find_stuck_documents

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://unused",
        redis_url="redis://unused",
        upload_dir=str(tmp_path),
        stuck_after_minutes=10,
        max_ingest_attempts=3,
    )


def _document(
    session_factory: sessionmaker[Session],
    status: DocumentStatus,
    *,
    minutes_ago: int,
    attempts: int = 1,
) -> uuid.UUID:
    moment = NOW - timedelta(minutes=minutes_ago)
    with session_factory() as session, session.begin():
        document = Document(
            organization_id="org-a",
            filename="c.pdf",
            sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            size_bytes=1,
            status=status,
            attempts=attempts,
            processing_started_at=moment if status == DocumentStatus.PROCESSING else None,
            updated_at=moment,
        )
        session.add(document)
        session.flush()
        return document.id


def test_requeues_documents_stuck_in_processing_or_pending(
    session_factory: sessionmaker[Session], settings: Settings
) -> None:
    stuck_processing = _document(session_factory, DocumentStatus.PROCESSING, minutes_ago=30)
    stuck_pending = _document(session_factory, DocumentStatus.PENDING, minutes_ago=30)
    recent = _document(session_factory, DocumentStatus.PROCESSING, minutes_ago=2)
    ready = _document(session_factory, DocumentStatus.READY, minutes_ago=30)

    requeued = find_stuck_documents(session_factory, settings, NOW)

    assert set(requeued) == {stuck_processing, stuck_pending}
    assert recent not in requeued and ready not in requeued


def test_does_not_requeue_twice_in_a_row(
    session_factory: sessionmaker[Session], settings: Settings
) -> None:
    _document(session_factory, DocumentStatus.PROCESSING, minutes_ago=30)

    assert len(find_stuck_documents(session_factory, settings, NOW)) == 1
    assert find_stuck_documents(session_factory, settings, NOW) == []


def test_marks_failed_after_max_attempts(
    session_factory: sessionmaker[Session], settings: Settings
) -> None:
    document_id = _document(session_factory, DocumentStatus.PROCESSING, minutes_ago=30, attempts=3)

    assert find_stuck_documents(session_factory, settings, NOW) == []

    with session_factory() as session:
        document = session.get_one(Document, document_id)
    assert document.status == DocumentStatus.FAILED
    assert document.error_code == "STUCK"
