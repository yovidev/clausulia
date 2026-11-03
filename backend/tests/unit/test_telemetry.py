import json

import pytest
from celery import Celery
from opentelemetry import trace
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app.api.errors import error_response
from app.core.logging import add_trace_context
from app.core.telemetry import timed_span

tracer = trace.get_tracer(__name__)


def test_log_processor_adds_trace_ids_inside_a_span(span_exporter: InMemorySpanExporter) -> None:
    with tracer.start_as_current_span("operacion") as span:
        event = add_trace_context(None, "info", {"event": "hola"})
        context = span.get_span_context()

    assert event["trace_id"] == format(context.trace_id, "032x")
    assert event["span_id"] == format(context.span_id, "016x")
    assert len(event["trace_id"]) == 32
    assert len(event["span_id"]) == 16


def test_log_processor_adds_nothing_outside_a_span(span_exporter: InMemorySpanExporter) -> None:
    event = add_trace_context(None, "info", {"event": "hola"})

    assert event == {"event": "hola"}


def test_error_response_includes_active_trace_id(span_exporter: InMemorySpanExporter) -> None:
    with tracer.start_as_current_span("peticion") as span:
        response = error_response(404, "NOT_FOUND", "No existe")
        trace_id = format(span.get_span_context().trace_id, "032x")

    assert json.loads(response.body)["error"]["trace_id"] == trace_id
    outside = error_response(404, "NOT_FOUND", "No existe")
    assert json.loads(outside.body)["error"]["trace_id"] == ""


def test_timed_span_records_duration_and_marks_errors(
    span_exporter: InMemorySpanExporter,
) -> None:
    with timed_span(tracer, "bien", {"a": 1}):
        pass
    with pytest.raises(ValueError), timed_span(tracer, "mal", duration_attribute="mal.ms"):
        raise ValueError("fallo")

    ok, failed = span_exporter.get_finished_spans()
    assert ok.attributes is not None and failed.attributes is not None
    assert ok.attributes["a"] == 1
    assert isinstance(ok.attributes["bien.duration_ms"], float)
    assert "mal.ms" in failed.attributes
    assert failed.status.status_code == StatusCode.ERROR
    assert [e.name for e in failed.events] == ["exception"]


def test_trace_context_travels_in_celery_message_headers(
    span_exporter: InMemorySpanExporter,
) -> None:
    """Lo que publica la API lleva traceparent: el worker continúa la misma traza."""
    app = Celery("propagation-test", broker="memory://")

    @app.task(name="echo")
    def echo(value: int) -> int:
        return value

    instrumentor = CeleryInstrumentor()
    instrumentor.instrument()
    try:
        with tracer.start_as_current_span("POST /documents") as span:
            echo.apply_async(args=[1])
            trace_id = format(span.get_span_context().trace_id, "032x")
        with app.connection_for_read() as connection:
            queue = connection.SimpleQueue("celery")
            message = queue.get(timeout=2)
            headers = message.headers
            message.ack()
            queue.close()
    finally:
        instrumentor.uninstrument()

    # traceparent = versión-trace_id-span_id-flags (W3C Trace Context)
    _, header_trace_id, _, _ = headers["traceparent"].split("-")
    assert header_trace_id == trace_id
    publish = next(s for s in span_exporter.get_finished_spans() if s.name.startswith("apply"))
    assert publish.context is not None
    assert format(publish.context.trace_id, "032x") == trace_id
