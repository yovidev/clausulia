"""Aplicación FastAPI: routers y manejo uniforme de errores."""

import kombu.exceptions
import redis.exceptions
import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import documents, health
from app.api.errors import ApiError, error_response

log = structlog.get_logger(__name__)

# Fallos al publicar en la cola (Redis caído o inalcanzable).
BROKER_ERRORS: tuple[type[Exception], ...] = (
    kombu.exceptions.OperationalError,
    redis.exceptions.ConnectionError,
    redis.exceptions.TimeoutError,
)

HTTP_CODES = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message)


async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = ", ".join(".".join(str(part) for part in e["loc"]) for e in exc.errors())
    return error_response(422, "VALIDATION_ERROR", f"Datos de entrada inválidos: {fields}")


async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
    return error_response(exc.status_code, code, str(exc.detail))


async def handle_database_error(request: Request, exc: Exception) -> JSONResponse:
    log.error("database_unavailable", error=str(exc))
    return error_response(503, "DATABASE_UNAVAILABLE", "La base de datos no está disponible")


async def handle_broker_error(request: Request, exc: Exception) -> JSONResponse:
    log.error("queue_unavailable", error=str(exc))
    return error_response(
        503,
        "QUEUE_UNAVAILABLE",
        "La cola de procesamiento no está disponible; el documento se procesará más tarde",
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_error")
    return error_response(500, "INTERNAL_ERROR", "Error interno del servidor")


def create_app() -> FastAPI:
    app = FastAPI(title="Clausulia")
    app.include_router(health.router)
    app.include_router(documents.router)

    # El decorador acepta handlers tipados con su excepción concreta.
    app.exception_handler(ApiError)(handle_api_error)
    app.exception_handler(RequestValidationError)(handle_validation_error)
    app.exception_handler(StarletteHTTPException)(handle_http_error)
    app.exception_handler(OperationalError)(handle_database_error)
    for error in BROKER_ERRORS:
        app.exception_handler(error)(handle_broker_error)
    app.exception_handler(Exception)(handle_unexpected_error)
    return app


app = create_app()
