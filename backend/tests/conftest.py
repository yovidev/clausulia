import os

# Antes de importar la app: en tests nunca se exportan trazas (ni hay Jaeger al que enviarlas).
os.environ["OTEL_ENABLED"] = "false"

from collections.abc import Iterator  # noqa: E402  el entorno debe fijarse antes

import pytest  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)


@pytest.fixture(scope="session")
def _memory_exporter() -> InMemorySpanExporter:
    # El provider global solo puede fijarse una vez por proceso: se comparte en la sesión.
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


@pytest.fixture
def span_exporter(_memory_exporter: InMemorySpanExporter) -> Iterator[InMemorySpanExporter]:
    """Spans terminados durante el test, guardados en memoria."""
    _memory_exporter.clear()
    yield _memory_exporter
    _memory_exporter.clear()
