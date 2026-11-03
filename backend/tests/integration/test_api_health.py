from collections.abc import Iterator

import pytest
import redis
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.main import app

pytestmark = pytest.mark.integration


class FakeRedis:
    """Doble del cliente de Redis: responde al ping o falla como si estuviera caído."""

    def __init__(self, up: bool) -> None:
        self.up = up

    def ping(self) -> bool:
        if not self.up:
            raise redis.ConnectionError("Error 111 connecting to redis")
        return True

    def close(self) -> None:
        pass


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    def override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    settings = Settings(database_url="postgresql+psycopg://unused", redis_url="redis://fake")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _fake_redis(monkeypatch: pytest.MonkeyPatch, *, up: bool) -> None:
    monkeypatch.setattr(redis.Redis, "from_url", lambda *args, **kwargs: FakeRedis(up))


def test_health_ok_when_postgres_and_redis_are_up(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_redis(monkeypatch, up=True)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "postgres": "ok", "redis": "ok"}


def test_health_503_when_redis_ping_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_redis(monkeypatch, up=False)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "postgres": "ok", "redis": "down"}
