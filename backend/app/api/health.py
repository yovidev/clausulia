"""Comprobación de salud de las dependencias."""

from typing import Annotated, Literal

import redis
import structlog
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db

log = structlog.get_logger(__name__)
router = APIRouter(tags=["health"])

Status = Literal["ok", "down"]


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    postgres: Status
    redis: Status


@router.get("/health", response_model=HealthOut, responses={503: {"model": HealthOut}})
def health(
    response: Response,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthOut:
    postgres = _check_postgres(session)
    redis_status = _check_redis(settings.redis_url)
    healthy = postgres == "ok" and redis_status == "ok"
    if not healthy:
        response.status_code = 503
    return HealthOut(status="ok" if healthy else "degraded", postgres=postgres, redis=redis_status)


def _check_postgres(session: Session) -> Status:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        log.warning("health_postgres_down")
        return "down"
    return "ok"


def _check_redis(redis_url: str) -> Status:
    client = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        client.ping()
    except redis.RedisError:
        log.warning("health_redis_down")
        return "down"
    finally:
        client.close()
    return "ok"
