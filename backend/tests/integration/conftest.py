import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

# Solo en local: si no hay backend/.env no hace nada, y nunca pisa variables ya definidas.
load_dotenv()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        # En CI (GitHub define CI=true) saltarse los tests dejaría el job en verde sin probar nada.
        if os.environ.get("CI"):
            pytest.fail("TEST_DATABASE_URL no está definida en CI", pytrace=False)
        pytest.skip("TEST_DATABASE_URL no está definida")
    _check_reachable(url)
    # Alembic lee la URL desde la configuración: la apuntamos a la base de pruebas.
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")  # de paso, prueba la migración
    test_engine = create_engine(url)
    yield test_engine
    test_engine.dispose()


def _check_reachable(url: str) -> None:
    """Falla en segundos si la base no responde (sin timeout, psycopg puede esperar sin fin)."""
    probe = create_engine(url, connect_args={"connect_timeout": 5})
    try:
        with probe.connect():
            pass
    except OperationalError as exc:
        pytest.fail(f"No se pudo conectar a TEST_DATABASE_URL: {exc.orig}", pytrace=False)
    finally:
        probe.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE chunks, documents CASCADE"))
    return sessionmaker(bind=engine, expire_on_commit=False)
