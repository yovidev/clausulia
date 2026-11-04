import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Document, DocumentStatus
from app.worker import tasks

pytestmark = pytest.mark.integration


def test_embedder_that_never_loads_ends_failed_after_retries(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    with session_factory() as session, session.begin():
        document = Document(
            organization_id="org-a", filename="contrato.pdf", sha256="b" * 64, size_bytes=10
        )
        session.add(document)
        session.flush()
        document_id = document.id

    calls = 0

    def broken_embedder() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("descarga del modelo interrumpida")

    monkeypatch.setattr(tasks, "get_embedder", broken_embedder)
    monkeypatch.setattr(tasks, "get_session_factory", lambda: session_factory)

    # apply() ejecuta en el proceso, sin broker; en ese modo self.retry también reejecuta
    # la tarea en el acto (sin esperar el countdown), así que se recorren todos los intentos.
    result = tasks.ingest_document.apply(args=[str(document_id)])

    assert result.failed()
    assert isinstance(result.result, tasks.EmbeddingsUnavailableError)
    assert calls == tasks.MAX_RETRIES + 1
    with session_factory() as session:
        stored = session.get_one(Document, document_id)
        assert stored.status == DocumentStatus.FAILED
        assert stored.error_code == "EMBEDDINGS_UNAVAILABLE"
        # Nunca llegó a reclamarse: el fallo es anterior a la ingesta.
        assert stored.attempts == 0
