"""Logs en JSON con structlog, incluidos los de uvicorn y celery, con trace_id y span_id."""

import logging
import sys

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from app.core.telemetry import current_trace_ids


def add_trace_context(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """Añade trace_id y span_id del span activo para cruzar logs con trazas en Jaeger."""
    ids = current_trace_ids()
    if ids is not None:
        event_dict["trace_id"], event_dict["span_id"] = ids
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Un único handler en el logger raíz que formatea todo en JSON.

    Los logs de structlog y los de la librería estándar (uvicorn, celery, sqlalchemy)
    pasan por los mismos procesadores.
    """
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_trace_context,
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # uvicorn instala sus propios handlers: se quitan para que todo salga por el raíz.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "celery"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
