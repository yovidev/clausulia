from typing import Any

from celery import Celery, signals

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.telemetry import setup_telemetry, shutdown_telemetry

settings = get_settings()

celery_app = Celery("clausulia", broker=settings.redis_url, include=["app.worker.tasks"])

celery_app.conf.update(
    # Confirmar la tarea al terminar, no al recibirla: si el worker muere, se reentrega.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Cada proceso toma una tarea a la vez, para no retener tareas que otro podría hacer.
    worker_prefetch_multiplier=1,
    # No guardamos resultados: el estado real está en la tabla documents.
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 3600},
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "recover-stuck-documents": {
            "task": "recover_stuck_documents",
            "schedule": 300.0,  # cada 5 minutos
        }
    },
)


@signals.setup_logging.connect(weak=False)
def _configure_logging(**kwargs: Any) -> None:
    # Conectar esta señal evita que Celery configure su propio formato de logs.
    configure_logging(settings.log_level)


@signals.worker_process_init.connect(weak=False)
def _init_telemetry(**kwargs: Any) -> None:
    # Con prefork cada proceso hijo necesita su propio provider (el BatchSpanProcessor usa
    # un hilo, y los hilos no sobreviven al fork). Por eso no se configura en el padre.
    setup_telemetry(settings.otel_service_name or "clausulia-worker", settings)


@signals.worker_process_shutdown.connect(weak=False)
def _shutdown_telemetry(**kwargs: Any) -> None:
    shutdown_telemetry()
