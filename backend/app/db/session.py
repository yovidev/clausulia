from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    # pool_pre_ping detecta conexiones muertas (por ejemplo, si Postgres se reinició).
    # connect_timeout: sin él, psycopg puede esperar sin fin a un Postgres que no responde;
    # con él, la conexión falla en 5 s y la API devuelve 503 DATABASE_UNAVAILABLE.
    return create_engine(
        get_settings().database_url, pool_pre_ping=True, connect_args={"connect_timeout": 5}
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesión por petición, siempre cerrada al final."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
