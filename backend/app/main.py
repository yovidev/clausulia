"""Aplicación FastAPI: routers y manejo uniforme de errores."""

import math

import kombu.exceptions
import redis.exceptions
import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import ask, documents, health
from app.api.errors import ApiError, error_response
from app.api.validation import validation_message
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.telemetry import setup_telemetry
from app.llm.base import LLMProviderError, LLMRateLimitError, LLMTimeoutError
from app.rag.errors import DocumentNotFoundError, DocumentNotReadyError

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
    return error_response(422, "VALIDATION_ERROR", validation_message(exc.errors()))


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


async def handle_document_not_found(request: Request, exc: DocumentNotFoundError) -> JSONResponse:
    ids = ", ".join(str(i) for i in exc.document_ids)
    return error_response(404, "DOCUMENT_NOT_FOUND", f"Documentos no encontrados: {ids}")


async def handle_document_not_ready(request: Request, exc: DocumentNotReadyError) -> JSONResponse:
    ids = ", ".join(str(i) for i in exc.document_ids)
    return error_response(409, "DOCUMENT_NOT_READY", f"Documentos que aún no están listos: {ids}")


async def handle_llm_rate_limit(request: Request, exc: LLMRateLimitError) -> JSONResponse:
    headers = None
    if exc.retry_after is not None:
        headers = {"Retry-After": str(max(1, math.ceil(exc.retry_after)))}
    return error_response(
        429,
        "LLM_RATE_LIMITED",
        "El proveedor de LLM está limitando las peticiones; inténtalo más tarde",
        headers,
    )


async def handle_llm_timeout(request: Request, exc: LLMTimeoutError) -> JSONResponse:
    log.warning("llm_timeout", error=str(exc))
    return error_response(504, "LLM_TIMEOUT", "El proveedor de LLM no respondió a tiempo")


async def handle_llm_provider_error(request: Request, exc: LLMProviderError) -> JSONResponse:
    log.error("llm_provider_error", error=str(exc))
    return error_response(502, "LLM_PROVIDER_ERROR", "El proveedor de LLM devolvió un error")


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_error")
    return error_response(500, "INTERNAL_ERROR", "Error interno del servidor")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="Clausulia")
    if setup_telemetry(settings.otel_service_name or "clausulia-api", settings):
        # /health se excluye: el healthcheck de Docker llenaría Jaeger de trazas sin interés.
        FastAPIInstrumentor.instrument_app(app, excluded_urls="health")
    app.include_router(health.router)
    app.include_router(documents.router)
    app.include_router(ask.router)

    # El decorador acepta handlers tipados con su excepción concreta.
    app.exception_handler(ApiError)(handle_api_error)
    app.exception_handler(RequestValidationError)(handle_validation_error)
    app.exception_handler(StarletteHTTPException)(handle_http_error)
    app.exception_handler(OperationalError)(handle_database_error)
    for error in BROKER_ERRORS:
        app.exception_handler(error)(handle_broker_error)
    app.exception_handler(DocumentNotFoundError)(handle_document_not_found)
    app.exception_handler(DocumentNotReadyError)(handle_document_not_ready)
    app.exception_handler(LLMRateLimitError)(handle_llm_rate_limit)
    app.exception_handler(LLMTimeoutError)(handle_llm_timeout)
    app.exception_handler(LLMProviderError)(handle_llm_provider_error)
    app.exception_handler(Exception)(handle_unexpected_error)
    return app


app = create_app()
