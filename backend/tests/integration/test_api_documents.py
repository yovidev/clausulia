import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import kombu.exceptions
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api import documents as documents_api
from app.api.deps import get_enqueuer
from app.core.config import Settings, get_settings
from app.db.models import EMBEDDING_DIM, Chunk, Document, DocumentStatus
from app.db.session import get_db
from app.main import app
from tests.factories import make_pdf

pytestmark = pytest.mark.integration


class FakeQueue:
    """Doble de enqueue_ingestion: guarda los ids o simula Redis caído."""

    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []
        self.broken = False

    def __call__(self, document_id: uuid.UUID) -> None:
        if self.broken:
            raise kombu.exceptions.OperationalError("Error 111 connecting to redis")
        self.enqueued.append(document_id)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://unused",
        redis_url="redis://unused",
        upload_dir=str(tmp_path / "uploads"),
        max_upload_mb=1,
    )


@pytest.fixture
def queue() -> FakeQueue:
    return FakeQueue()


@pytest.fixture
def client(
    session_factory: sessionmaker[Session], settings: Settings, queue: FakeQueue
) -> Iterator[TestClient]:
    def override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_enqueuer] = lambda: queue
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def pdf_bytes(tmp_path: Path) -> bytes:
    return make_pdf(tmp_path / "contrato.pdf", ["Plazo de pago: 30 días"]).read_bytes()


def _upload(
    client: TestClient, content: bytes, org: str | None = None, name: str = "contrato.pdf"
) -> httpx.Response:
    headers = {"X-Org-Id": org} if org is not None else {}
    return client.post(
        "/documents", files={"file": (name, content, "application/pdf")}, headers=headers
    )


def test_new_upload_returns_202_saves_file_and_enqueues(
    client: TestClient, queue: FakeQueue, settings: Settings, pdf_bytes: bytes
) -> None:
    response = _upload(client, pdf_bytes)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["duplicate"] is False
    assert body["filename"] == "contrato.pdf"
    assert body["size_bytes"] == len(pdf_bytes)
    assert queue.enqueued == [uuid.UUID(body["id"])]
    stored = Path(settings.upload_dir) / f"{body['sha256']}.pdf"
    assert stored.read_bytes() == pdf_bytes
    assert list(Path(settings.upload_dir).glob("*.part")) == []


def test_duplicate_in_same_org_returns_200_with_existing_document(
    client: TestClient, queue: FakeQueue, pdf_bytes: bytes
) -> None:
    first = _upload(client, pdf_bytes, org="org-a").json()
    second = _upload(client, pdf_bytes, org="org-a", name="otro-nombre.pdf")

    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["id"] == first["id"]
    assert len(queue.enqueued) == 1


def test_same_file_in_other_org_creates_separate_document(
    client: TestClient, queue: FakeQueue, pdf_bytes: bytes
) -> None:
    first = _upload(client, pdf_bytes, org="org-a").json()
    second = _upload(client, pdf_bytes, org="org-b")

    assert second.status_code == 202
    assert second.json()["id"] != first["id"]
    assert len(queue.enqueued) == 2


def test_duplicate_of_failed_document_is_reset_and_requeued(
    client: TestClient,
    queue: FakeQueue,
    session_factory: sessionmaker[Session],
    pdf_bytes: bytes,
) -> None:
    document_id = uuid.UUID(_upload(client, pdf_bytes).json()["id"])
    with session_factory() as session, session.begin():
        document = session.get_one(Document, document_id)
        document.status = DocumentStatus.FAILED
        document.error_code = "INGESTION_FAILED"
        document.error_message = "falló"
        document.attempts = 5

    response = _upload(client, pdf_bytes)

    assert response.status_code == 200
    body = response.json()
    assert body["duplicate"] is True
    assert body["status"] == "pending"
    assert body["error_code"] is None
    assert queue.enqueued == [document_id, document_id]
    with session_factory() as session:
        assert session.get_one(Document, document_id).attempts == 0


def test_concurrent_duplicate_is_resolved_via_integrity_error(
    client: TestClient,
    queue: FakeQueue,
    pdf_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _upload(client, pdf_bytes).json()

    # Simula la carrera: la primera búsqueda no ve el documento que otra petición ya insertó.
    real_find = documents_api._find_existing
    calls: list[int] = []

    def racy_find(session: Session, org_id: str, sha256: str) -> Document | None:
        calls.append(1)
        return None if len(calls) == 1 else real_find(session, org_id, sha256)

    monkeypatch.setattr(documents_api, "_find_existing", racy_find)
    response = _upload(client, pdf_bytes)

    assert response.status_code == 200
    assert response.json()["duplicate"] is True
    assert response.json()["id"] == first["id"]
    assert len(calls) == 2
    assert len(queue.enqueued) == 1


def test_non_pdf_is_rejected_with_415(
    client: TestClient, queue: FakeQueue, settings: Settings
) -> None:
    response = _upload(client, b"esto no es un pdf", name="falso.pdf")

    assert response.status_code == 415
    assert response.json() == {
        "error": {
            "code": "UNSUPPORTED_FILE_TYPE",
            "message": "El archivo no es un PDF",
            "trace_id": "",
        }
    }
    assert queue.enqueued == []
    assert list(Path(settings.upload_dir).iterdir()) == []


def test_file_too_large_is_rejected_with_413(
    client: TestClient, queue: FakeQueue, settings: Settings
) -> None:
    content = b"%PDF-1.7\n" + b"0" * (1024 * 1024)  # algo más de 1 MB

    response = _upload(client, content)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert queue.enqueued == []
    assert list(Path(settings.upload_dir).iterdir()) == []


@pytest.mark.parametrize("org", ["", "con espacio", "a" * 65, "org/../x"])
def test_invalid_org_header_is_rejected_with_422(
    client: TestClient, pdf_bytes: bytes, org: str
) -> None:
    response = _upload(client, pdf_bytes, org=org)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "X-Org-Id" in response.json()["error"]["message"]


def test_default_org_is_used_without_header(
    client: TestClient, settings: Settings, pdf_bytes: bytes
) -> None:
    document_id = _upload(client, pdf_bytes).json()["id"]

    response = client.get(
        f"/documents/{document_id}", headers={"X-Org-Id": settings.default_org_id}
    )
    assert response.status_code == 200


def test_get_document_is_isolated_by_org(client: TestClient, pdf_bytes: bytes) -> None:
    document_id = _upload(client, pdf_bytes, org="org-a").json()["id"]

    own = client.get(f"/documents/{document_id}", headers={"X-Org-Id": "org-a"})
    other = client.get(f"/documents/{document_id}", headers={"X-Org-Id": "org-b"})

    assert own.status_code == 200
    assert other.status_code == 404
    assert other.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def _set_created_at(session_factory: sessionmaker[Session], times: dict[str, datetime]) -> None:
    """Fija created_at a mano: dos subidas seguidas pueden tener la misma marca (o incluso
    invertida si el reloj de la máquina virtual de Docker se reajusta)."""
    with session_factory() as session, session.begin():
        for document_id, created_at in times.items():
            session.get_one(Document, uuid.UUID(document_id)).created_at = created_at


def test_list_documents_is_isolated_and_newest_first(
    client: TestClient, session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    older = make_pdf(tmp_path / "1.pdf", ["uno"]).read_bytes()
    newer = make_pdf(tmp_path / "2.pdf", ["dos"]).read_bytes()
    first = _upload(client, older, org="org-a").json()["id"]
    second = _upload(client, newer, org="org-a").json()["id"]
    _upload(client, older, org="org-b")
    now = datetime.now(UTC)
    _set_created_at(session_factory, {first: now - timedelta(minutes=1), second: now})

    response = client.get("/documents", headers={"X-Org-Id": "org-a"})

    assert response.status_code == 200
    assert [d["id"] for d in response.json()["items"]] == [second, first]


def test_list_documents_breaks_ties_by_id(
    client: TestClient, session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    ids = [
        _upload(client, make_pdf(tmp_path / f"{i}.pdf", [f"doc {i}"]).read_bytes()).json()["id"]
        for i in range(3)
    ]
    same = datetime.now(UTC)
    _set_created_at(session_factory, dict.fromkeys(ids, same))

    response = client.get("/documents")

    assert [d["id"] for d in response.json()["items"]] == sorted(ids)


def test_get_chunk_is_isolated_by_org(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session, session.begin():
        document = Document(
            organization_id="org-a",
            filename="contrato.pdf",
            sha256="a" * 64,
            size_bytes=10,
            status=DocumentStatus.READY,
        )
        chunk = Chunk(
            document=document,
            chunk_index=0,
            page_number=3,
            content="El plazo de pago es de 30 días.",
            embedding=[0.0] * EMBEDDING_DIM,
        )
        session.add_all([document, chunk])
    chunk_id = chunk.id

    own = client.get(f"/chunks/{chunk_id}", headers={"X-Org-Id": "org-a"})
    other = client.get(f"/chunks/{chunk_id}", headers={"X-Org-Id": "org-b"})

    assert own.status_code == 200
    assert own.json()["page_number"] == 3
    assert own.json()["filename"] == "contrato.pdf"
    assert other.status_code == 404
    assert other.json()["error"]["code"] == "CHUNK_NOT_FOUND"


def test_redis_down_returns_503_and_document_stays_pending(
    client: TestClient,
    queue: FakeQueue,
    session_factory: sessionmaker[Session],
    pdf_bytes: bytes,
) -> None:
    queue.broken = True

    response = _upload(client, pdf_bytes, org="org-a")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "QUEUE_UNAVAILABLE"
    with session_factory() as session:
        document = session.scalars(
            select(Document).where(Document.organization_id == "org-a")
        ).one()
        assert document.status == DocumentStatus.PENDING
