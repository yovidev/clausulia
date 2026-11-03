"""Trazas OpenTelemetry exportadas por OTLP gRPC directamente a Jaeger (sin métricas)."""

import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span
from opentelemetry.util.types import AttributeValue

from app.core.config import Settings, get_settings
from app.db.session import get_engine

log = structlog.get_logger(__name__)

_provider: TracerProvider | None = None


def setup_telemetry(service_name: str, settings: Settings | None = None) -> bool:
    """Configura el TracerProvider e instrumenta SQLAlchemy, Redis y Celery.

    Idempotente: la segunda llamada no hace nada. Con OTEL_ENABLED=false no se configura
    nada y los spans son no-op. Devuelve True si la telemetría quedó activa.
    """
    global _provider
    settings = settings or get_settings()
    if _provider is not None:
        return True
    if not settings.otel_enabled:
        return False

    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
    )
    trace.set_tracer_provider(provider)
    _provider = provider

    SQLAlchemyInstrumentor().instrument(engine=get_engine())
    RedisInstrumentor().instrument()
    CeleryInstrumentor().instrument()  # type: ignore[no-untyped-call]  # paquete sin tipos
    log.info("telemetry_enabled", service=service_name)
    return True


def shutdown_telemetry() -> None:
    """Envía los spans pendientes antes de que termine el proceso."""
    if _provider is not None:
        _provider.shutdown()


@contextmanager
def timed_span(
    tracer: trace.Tracer,
    name: str,
    attributes: Mapping[str, AttributeValue] | None = None,
    duration_attribute: str | None = None,
) -> Iterator[Span]:
    """Span con su duración en ms como atributo (<name>.duration_ms por defecto).

    Si el bloque lanza una excepción, el span queda en ERROR y la registra.
    """
    start = time.perf_counter()
    with tracer.start_as_current_span(name, attributes=attributes) as span:
        try:
            yield span
        finally:
            elapsed = round((time.perf_counter() - start) * 1000, 1)
            span.set_attribute(duration_attribute or f"{name}.duration_ms", elapsed)


def current_trace_ids() -> tuple[str, str] | None:
    """(trace_id, span_id) en hexadecimal del span activo, o None si no hay ninguno."""
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return format(context.trace_id, "032x"), format(context.span_id, "016x")
