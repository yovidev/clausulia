# Clausulia: contexto para Claude Code

Prueba técnica de TopDevCrew (Ingeniero AI Full Stack Semi-Senior). Entrega: miércoles 5 de noviembre de 2026, 23:19 UTC (18:19 hora de Cuba). Una sola entrega: se evalúa el último commit al pegar el link, y el autor defiende el código línea por línea en una entrevista.

## Qué es

MVP RAG con citas para contratos de proveedores. El analista sube PDFs; un worker los procesa en segundo plano (extracción de texto, chunking, embeddings) y los guarda en PostgreSQL con pgvector. Luego pregunta en lenguaje natural y recibe respuestas con citas a documento y página. Si no hay evidencia suficiente, el sistema lo dice en lugar de inventar. Todo trazable con OpenTelemetry.

## Reglas de trabajo

- Trabaja **una pieza a la vez**, solo lo que pide el prompt. No adelantes pasos ni refactorices lo que ya funciona sin pedirlo.
- **No cambies decisiones ya tomadas** (sección "Decisiones") sin preguntar antes y explicar por qué.
- Cada pieza lleva sus tests. Tras cada cambio, ejecuta desde `backend/`: `uv run ruff check .`, `uv run ruff format .`, `uv run mypy app`, `uv run pytest -v`. No termines con nada en rojo.
- **No hagas commit ni push.** El autor revisa y commitea.
- Al terminar, resume: archivos creados o modificados, qué hace cada uno, decisiones nuevas que haya que anotar en DECISIONS.md, y cualquier cosa que el autor deba verificar a mano.
- Código simple y explicable. Nada de abstracciones que no se usen.
- Nunca escribas secretos en el código ni en el repo. Todo por variables de entorno.

## Entorno del autor

- Windows con **PowerShell 7**. Nada de sintaxis Bash (`mkdir -p a/{b,c}`, `&&` encadenando, `export`). Usa sintaxis de PowerShell.
- Python 3.12 gestionado con **uv** dentro de `backend/` (`uv run ...`, `uv add ...`). Nunca pip.
- Conexión lenta: evita dependencias nuevas salvo que sean necesarias, y avisa antes de añadir alguna.
- Docker Desktop con Compose v2. La imagen del backend es `clausulia-backend`.
- Hay otros proyectos ocupando puertos. Puertos de este proyecto **hacia el host**:
  - Postgres: `localhost:55432` (dentro de Docker: `postgres:5432`)
  - Redis: `localhost:6380` (dentro de Docker: `redis:6379`)
  - Jaeger UI: `localhost:16686`; OTLP gRPC `4317`, HTTP `4318`
  - Flower: `localhost:5555`
- `backend/.env` es para desarrollo local (usa `localhost` y los puertos de arriba). El `.env` de la raíz es para Docker (usa nombres de servicio). Ninguno se sube.
- Base de pruebas: `clausulia_test`, vía `TEST_DATABASE_URL` en `backend/.env`.
- Frontend con **pnpm** (no npm).

## Convenciones

- Identificadores en inglés; comentarios, docstrings y mensajes al usuario en español.
- Códigos de error en MAYÚSCULAS (`INVALID_PDF`, `NO_TEXT_LAYER`, `FILE_MISSING`...).
- Ruff con reglas `E, F, I, B, UP, S, SIM`, líneas de 100. Si hay que silenciar una regla, solo en esa línea, con `# noqa: XXX  motivo`.
- mypy en modo estricto sobre `app/`.
- Pydantic en los bordes (API y respuesta del LLM). Dataclasses para datos internos.
- Dependencias inyectadas por parámetro (session_factory, extractor, embedder, settings), para poder probar sin Celery ni red.
- Tests: `tests/unit` (sin base de datos), `tests/integration` (Postgres real, marcados `integration`), marca `model` para los que descargan el modelo real (excluidos por defecto). Helper compartido `tests/factories.py` (`make_pdf`).

## Estado actual del código (backend/)

- `app/core/config.py`: `Settings` (pydantic-settings), validado al arrancar. `get_settings()` con `lru_cache`.
- `app/db/models.py`: `Document` y `Chunk`. `EMBEDDING_DIM = 384` (constante de esquema). `UNIQUE (organization_id, sha256)`, `UNIQUE (document_id, chunk_index)`, índice HNSW coseno. Enum `DocumentStatus`: pending, processing, ready, failed. Campos `attempts` y `processing_started_at`.
- `app/db/session.py`: `get_engine()`, `get_session_factory()`, `get_db()` (dependencia FastAPI). SQLAlchemy 2 **síncrono** + psycopg 3.
- `migrations/`: Alembic. Migración inicial `06991eb44464` (crea extensión vector; al revertir borra el enum).
- `app/ingestion/chunking.py`: función pura `chunk_pages`. Por página, nunca cruza páginas, párrafos → oraciones → palabras, solapamiento empezando en palabra completa, nunca supera `chunk_size` caracteres.
- `app/ingestion/extraction.py`: `PdfExtractor` (Protocol) y `PypdfExtractor`. `PdfExtractionError(code, message)` para errores permanentes: `INVALID_PDF`, `ENCRYPTED_PDF`, `TOO_MANY_PAGES`, `NO_TEXT_LAYER` (menos de 20 caracteres por página de media). Deja pasar `FileNotFoundError`.
- `app/ingestion/embeddings.py`: `Embedder` (Protocol), `FastEmbedEmbedder` (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384, verifica la dimensión al cargar) y `FakeEmbedder` (determinista, hash de palabras con blake2b). `get_embedder()` según `EMBEDDING_PROVIDER` (`fastembed` | `fake`).
- `app/ingestion/storage.py`: `upload_path(upload_dir, sha256)`; los archivos se guardan como `<sha256>.pdf` y el hash se valida.
- `app/ingestion/service.py`: `run_ingestion` en tres fases: reclamar (FOR UPDATE, marca processing, +1 intento), procesar fuera de transacción, guardar de forma atómica (FOR UPDATE, borrar chunks, insertar en lote, marcar ready). `mark_failed`.
- `app/ingestion/recovery.py`: `find_stuck_documents` (pending/processing con más de `stuck_after_minutes`; reencola o marca `STUCK` al llegar a `max_ingest_attempts`; `skip_locked`).
- `app/worker/celery_app.py`: `acks_late`, `reject_on_worker_lost`, `prefetch_multiplier=1`, `ignore_result`, `visibility_timeout=3600`, beat cada 5 minutos.
- `app/worker/tasks.py`: `ingest_document` (reintenta solo `OperationalError`, `ConnectionError` y `TimeoutError`, con backoff exponencial y jitter, máximo 5; al agotar, `INGESTION_FAILED`), `recover_stuck_documents`, `enqueue_ingestion(document_id)` (punto único para encolar desde la API).
- Tests: 36 en verde (unitarios de chunking, extracción, embeddings y backoff; de integración de ingesta y recuperación).
- `docker-compose.yml`: postgres (pgvector/pgvector:pg16), redis (redis:7-alpine), jaeger (jaegertracing/jaeger, v2).
- `backend/Dockerfile`: python:3.12-slim + uv 0.13.6, dependencias en una capa separada, usuario sin privilegios `app` (uid 1000).

## Decisiones (no cambiar sin preguntar)

- Aislamiento: `organization_id` en documentos; header `X-Org-Id` (por defecto `default`); **todas** las consultas filtran por organización, incluida la vectorial. Sin autenticación en el MVP.
- Duplicados: mismo sha256 en la misma organización → 200 con el documento existente y `duplicate: true`; si estaba `failed`, se reencola. Distinta organización → documento separado.
- Límites: 20 MB, 500 páginas, solo PDF verificado por magic bytes `%PDF-`; cifrados rechazados.
- Evidencia: si ningún chunk supera el umbral → `insufficient_evidence` **sin llamar al LLM**. Contradicción entre documentos → mostrar ambas versiones con sus citas y `has_conflict: true`. Preguntas independientes, sin memoria de conversación.
- LLM: interfaz propia `LLMProvider`; `MockProvider` determinista (con modos de fallo: JSON inválido, timeout, 429) y `OpenAIProvider` (SDK oficial). Sin LiteLLM. Respuesta validada con Pydantic: `answer`, `citations` (ids de chunk), `confidence` (high, medium, low), `insufficient_evidence`. JSON inválido → un reintento con el error en el prompt; si vuelve a fallar → `status: rejected`. Citas a chunks no recuperados se descartan; sin citas válidas → `insufficient_evidence`. Confianza final = mínimo entre la del LLM y la derivada de la similitud. Timeout de 30 s; reintentos con backoff ante 429 y 5xx, respetando `Retry-After`.
- Prompt injection: chunks dentro de `<chunk id doc page>`, escapar etiquetas parecidas dentro del texto, system prompt que declara el contenido como datos, salida restringida al esquema.
- Errores HTTP: 413 tamaño, 415 no PDF, 422 validación, 404, 409 documento no listo, 429 / 502 / 504 del proveedor LLM, 503 Redis o Postgres caídos, 500 genérico sin detalles internos. Formato único: `{"error": {"code", "message", "trace_id"}}`.
- UI: polling cada 2 s solo mientras haya documentos pending o processing. React + Vite + TS + TanStack Query, pnpm.
- Observabilidad: OTLP directo a Jaeger (sin collector). Instrumentar FastAPI, Celery (en ambos lados; en el worker dentro de `worker_process_init`), SQLAlchemy y Redis. Spans manuales con atributos: `chunks.retrieved`, `similarity.top`, `llm.provider`, `llm.model`, `llm.tokens.input`, `llm.tokens.output`, `llm.retries`. Solo trazas: Jaeger no recibe métricas, así que no se configuran métricas OTel; las latencias van como atributos `*.duration_ms` de los spans, además de la duración propia de cada span. Logs structlog en JSON con `trace_id` y `span_id`.
- CI: GitHub Actions; backend con servicio `pgvector/pgvector:pg16`, `EMBEDDING_PROVIDER=fake`; frontend con pnpm.
- Chunking y recuperación: valores iniciales `CHUNK_SIZE=1000`, `CHUNK_OVERLAP=150`, `RETRIEVAL_K=6`, `SIMILARITY_THRESHOLD=0.35`. Se calibran con la evaluación (`eval/`).
