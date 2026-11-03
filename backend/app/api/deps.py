"""Dependencias compartidas por los routers (sustituibles en los tests)."""

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header

from app.core.config import Settings, get_settings
from app.worker.tasks import enqueue_ingestion

Enqueuer = Callable[[uuid.UUID], None]


def get_enqueuer() -> Enqueuer:
    return enqueue_ingestion


def get_org_id(
    settings: Annotated[Settings, Depends(get_settings)],
    x_org_id: Annotated[
        str | None, Header(alias="X-Org-Id", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    ] = None,
) -> str:
    """Organización de la petición. Sin autenticación en el MVP: se confía en el header."""
    return x_org_id if x_org_id is not None else settings.default_org_id
