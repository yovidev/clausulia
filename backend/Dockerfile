FROM python:3.12-slim

# uv copiado desde su imagen oficial, misma versión que usas en local
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_HTTP_TIMEOUT=300 \
    UV_CONCURRENT_DOWNLOADS=2 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) Solo dependencias: esta capa se reutiliza mientras no cambie uv.lock
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# 2) El código
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Usuario sin privilegios y carpeta para los PDFs subidos
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data/uploads \
    && chown -R app:app /data /app
USER app