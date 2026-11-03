import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

load_dotenv()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL no está definida")
    # Alembic lee la URL desde la configuración: la apuntamos a la base de pruebas.
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")  # de paso, prueba la migración
    test_engine = create_engine(url)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE chunks, documents CASCADE"))
    return sessionmaker(bind=engine, expire_on_commit=False)
