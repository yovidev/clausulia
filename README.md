# Clausulia

Asistente para consultar contratos de proveedores con respuestas citadas. El analista sube PDFs, un worker los procesa en segundo plano (texto, fragmentos y embeddings en PostgreSQL con pgvector) y después se pregunta en lenguaje natural. Cada respuesta cita documento y página; si no hay evidencia suficiente, el sistema lo dice en lugar de inventar. Todo el recorrido es trazable con OpenTelemetry en Jaeger.

Funciona sin claves de API: los embeddings se calculan con un modelo local y, por defecto, el LLM es un proveedor simulado y determinista.

## Arquitectura

```mermaid
flowchart LR
    U[Navegador] -->|:3000| F[frontend<br/>nginx + React]
    F -->|/api → :8000| A[api<br/>FastAPI]
    A -->|SQL + pgvector| P[(postgres<br/>pgvector)]
    A -->|encola la ingesta| R[(redis)]
    R --> W[worker<br/>Celery + beat]
    W -->|chunks y embeddings| P
    M[migrate<br/>Alembic] -->|una vez al arrancar| P
    FL[flower] --> R
    A -. OTLP gRPC .-> J[jaeger]
    W -. OTLP gRPC .-> J
```

| Servicio | Imagen | Qué hace |
|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | Base de datos con la extensión vector: documentos, fragmentos (chunks) y sus embeddings. |
| `redis` | `redis:7-alpine` | Broker de Celery: cola de tareas de ingesta. |
| `jaeger` | `jaegertracing/jaeger:latest` | Recibe las trazas por OTLP y las muestra en su interfaz web. Guarda en memoria: las trazas se pierden al reiniciarlo. |
| `migrate` | `clausulia-backend` | Ejecuta `alembic upgrade head` y termina. La API y el worker esperan a que acabe bien. |
| `api` | `clausulia-backend` | FastAPI: subida y validación de PDFs, listado de documentos, preguntas (`POST /ask`), salud (`/health`). No procesa PDFs: los encola. |
| `worker` | `clausulia-backend` | Celery con beat embebido: extrae el texto, trocea, calcula embeddings y guarda los chunks. Cada 5 minutos rescata documentos atascados. |
| `frontend` | build propio | nginx sirve la interfaz React y hace de proxy de `/api/*` hacia la API. |
| `flower` | `clausulia-backend` | Panel web para ver las tareas de Celery. |

La API, el worker, Flower y `migrate` usan la misma imagen del backend con distintos comandos. Volúmenes: `pgdata` (base de datos), `uploads` (PDFs subidos, compartido por API y worker) y `models` (caché del modelo de embeddings, compartida por API y worker).

## Requisitos

- Docker con Compose v2 (`docker compose ...`).

Nada más para usarlo. Para ejecutar los tests en local hacen falta además [uv](https://docs.astral.sh/uv/) (backend) y Node 22 con pnpm (frontend); ver [Tests](#tests).

## Cómo levantarlo

Desde la raíz del repositorio:

```bash
cp .env.example .env              # PowerShell: Copy-Item .env.example .env
docker compose up --build
```

El `.env` de la raíz lo leen los contenedores; los valores de `.env.example` ya funcionan tal cual (usan los nombres de servicio de Docker como host).

Qué esperar:

1. La primera vez se construyen las imágenes del backend y del frontend; tarda varios minutos según la conexión.
2. `migrate` crea el esquema y termina con código 0. Después arrancan `api`, `worker` y `flower`, y el `frontend` cuando la API pasa su healthcheck.
3. **El primer documento tarda más**: el worker descarga el modelo de embeddings (`paraphrase-multilingual-MiniLM-L12-v2` en ONNX, unos 240 MB en disco) al volumen `models`. Mientras tanto el documento aparece como `pending`: el modelo se carga antes de empezar a procesarlo. Las siguientes ingestas ya no descargan nada.
4. La primera pregunta también tarda unos segundos más: la API carga el modelo en memoria (lo lee del mismo volumen, así que no lo vuelve a descargar si el worker ya lo hizo).

Para parar: `docker compose down`. Para borrar también los datos (base, PDFs y modelo): `docker compose down -v`.

## URLs

| Qué | URL |
|---|---|
| Interfaz | http://localhost:3000 |
| Documentación de la API (Swagger) | http://localhost:8000/docs |
| Salud de la API | http://localhost:8000/health |
| Jaeger | http://localhost:16686 |
| Flower | http://localhost:5555 |

Hacia el host también se publican Postgres en `localhost:55432` y Redis en `localhost:6380` (útiles para los tests locales).

## Probarlo con los PDF de `samples/`

`samples/` contiene contratos ficticios generados por `backend/scripts/generate_samples.py`:

| Archivo | Contenido |
|---|---|
| `contrato_suministro_andinos.pdf` | Suministro de material de oficina con Suministros Andinos (4 páginas). Preaviso de **60 días**. |
| `contrato_logistica_andinos.pdf` | Logística con el mismo proveedor (3 páginas). Preaviso de **90 días**: se contradice a propósito con el anterior. |
| `contrato_transporte_penalara.pdf` | Transporte con Transportes Peñalara (3 páginas). |
| `contrato_software_nexoria.pdf` | Licencia de software de Nexoria (2 páginas). |
| `contrato_limpieza_brillo.pdf` | Limpieza (2 páginas). La cláusula 4 contiene un intento de prompt injection. |
| `contrato_mantenimiento_escaneado.pdf` | Una página que es solo una imagen: no tiene texto extraíble. |

1. Abre http://localhost:3000 y arrastra los seis PDF a la zona de subida (acepta varios a la vez).
2. Los documentos pasan de `pending` a `processing` y a `ready`; la lista se refresca sola mientras haya alguno en curso. El escaneado termina en `failed` con el motivo «El PDF no tiene texto seleccionable (posiblemente es un escaneo).» (código `NO_TEXT_LAYER`): no hay OCR.
3. Pregunta en el chat:

| Pregunta | Qué se espera |
|---|---|
| ¿Qué se descuenta si la empresa de limpieza se salta una limpieza programada? | Respuesta citando `contrato_limpieza_brillo.pdf`, página 2 (el 10 % de la factura). Esa página contiene la inyección: el texto se trata como datos. |
| ¿Cuánto debe abonar el operador logístico por cada día que se retrase la salida de un pedido? | Cita a `contrato_logistica_andinos.pdf`, página 2 (300 euros por día). |
| ¿Qué seguro de responsabilidad civil debe tener contratado el transportista? | «No hay evidencia suficiente»: ningún contrato habla de seguros y no se llama al LLM. |
| ¿Qué plazo de preaviso hay que dar para resolver los contratos con Suministros Andinos? | La recuperación trae las dos cláusulas en conflicto (60 días y 90 días). Ver la nota de abajo. |

Cada cita se puede pulsar para ver el fragmento original.

![Interfaz con documentos y una respuesta citada](docs/interfaz.png)

**Nota sobre el proveedor simulado (`LLM_PROVIDER=mock`, el valor por defecto).** No entiende la pregunta: responde con el inicio del primer fragmento que recibe y lo cita, con confianza media. Por eso el texto de la respuesta puede empezar por otra cláusula de la misma página, y **nunca marca un conflicto**: en la pregunta del preaviso cita solo uno de los dos contratos. La detección de contradicciones (`has_conflict` con citas de ambos documentos) la hace el LLM real; con el simulado se ven el flujo completo, las citas, la validación y el rechazo por falta de evidencia.

También se puede usar la API directamente desde http://localhost:8000/docs. La organización se indica con el header `X-Org-Id` (por defecto `default`, que es la que usa la interfaz).

## Ver una traza en Jaeger

1. Sube un documento o haz una pregunta.
2. Abre http://localhost:16686, elige el servicio `clausulia-api` y pulsa **Find Traces**.
3. Una pregunta aparece como `POST /ask`. Dentro se ven los spans `ask`, `embed_query`, `pgvector.search` (con las consultas SQL), `llm.generate` y `validate_answer`, con atributos como `chunks.retrieved`, `similarity.top`, `llm.provider`, `llm.model`, `llm.tokens.input`, `llm.tokens.output`, `llm.retries` y las latencias `*.duration_ms`.
4. Una subida aparece como `POST /documents` y continúa en el servicio `clausulia-worker` dentro de la misma traza: `run/ingest_document` → `ingest.document` → `pdf.extract`, `chunking`, `embeddings`, `db.write_chunks`.

Las respuestas de error de la API incluyen un `trace_id`, que también muestra la interfaz: se puede pegar en el buscador de Jaeger para ir a la traza exacta. Los logs de los contenedores son JSON con `trace_id` y `span_id`.

Capturas:

- Traza de una pregunta: [docs/jaeger-traza-ask.png](docs/jaeger-traza-ask.png)
- Traza de una ingesta (API → worker): [docs/jaeger-traza-ingesta.png](docs/jaeger-traza-ingesta.png)

## Variables de entorno

Todas las de `.env.example`. Se validan al arrancar: si falta una obligatoria o hay una incoherencia (por ejemplo, `CHUNK_OVERLAP` mayor o igual que `CHUNK_SIZE`, o `LLM_PROVIDER=openai` sin clave), la aplicación no arranca.

| Variable | Valor en `.env.example` | Qué hace |
|---|---|---|
| `POSTGRES_USER` | `clausulia` | Usuario que crea el contenedor de Postgres. |
| `POSTGRES_PASSWORD` | `clausulia` | Su contraseña. Cámbiala fuera de un entorno local. |
| `POSTGRES_DB` | `clausulia` | Base que crea el contenedor. |
| `DATABASE_URL` | `postgresql+psycopg://clausulia:clausulia@postgres:5432/clausulia` | Conexión de la API, el worker y las migraciones. Debe coincidir con las tres anteriores. |
| `REDIS_URL` | `redis://redis:6379/0` | Broker de Celery. |
| `UPLOAD_DIR` | `/data/uploads` | Carpeta de los PDFs subidos (volumen `uploads`). Se guardan como `<sha256>.pdf`. |
| `MAX_UPLOAD_MB` | `20` | Tamaño máximo del PDF (413 si se supera). nginx corta a 21 MB: si lo subes, cambia también `client_max_body_size` en `frontend/nginx.conf`. |
| `MAX_PAGES` | `500` | Páginas máximas por PDF (`TOO_MANY_PAGES`). |
| `EMBEDDING_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Modelo de fastembed. Debe producir vectores de 384 dimensiones (se comprueba al cargarlo). |
| `EMBEDDING_PROVIDER` | `fastembed` | `fastembed` (modelo real) o `fake` (determinista, para tests y CI). |
| `EMBEDDING_CACHE_DIR` | `/models` | Dónde se descarga el modelo (volumen `models`). |
| `EMBED_DOCUMENT_TITLE` | `false` | Antepone `Documento: <nombre>` al texto de cada chunk al vectorizarlo. Desactivada porque en la evaluación empeoró el rechazo correcto. Cambiarla exige reprocesar los documentos. |
| `CHUNK_SIZE` | `1000` | Tamaño máximo de cada fragmento, en caracteres. |
| `CHUNK_OVERLAP` | `150` | Solapamiento entre fragmentos consecutivos de la misma página. |
| `RETRIEVAL_K` | `6` | Fragmentos que se recuperan por pregunta y que recibe el LLM. |
| `SIMILARITY_THRESHOLD` | `0.50` | Similitud coseno mínima del mejor fragmento para llamar al LLM. Si no llega: `insufficient_evidence` sin llamar al LLM. |
| `RETRIEVAL_MODE` | `hybrid` | `vector` (solo similitud coseno) o `hybrid` (coseno + búsqueda full-text en español, combinadas con Reciprocal Rank Fusion). |
| `HYBRID_CANDIDATES` | `20` | Candidatos que aporta cada rama de la búsqueda híbrida antes de combinarlas. |
| `RRF_K` | `60` | Constante de Reciprocal Rank Fusion: cada lista suma 1 / (`RRF_K` + posición). |
| `CONFIDENCE_HIGH_SIMILARITY` | `0.6` | Similitud del mejor fragmento citado a partir de la cual la confianza puede ser alta. |
| `CONFIDENCE_MEDIUM_SIMILARITY` | `0.45` | Ídem para confianza media; por debajo, baja. La confianza final es la menor entre la del LLM y esta. |
| `LLM_PROVIDER` | `mock` | `mock` (simulado, sin claves) u `openai`. |
| `OPENAI_API_KEY` | vacío | Clave de OpenAI. Obligatoria con `LLM_PROVIDER=openai`. No aparece en logs ni errores. |
| `OPENAI_MODEL` | vacío | Modelo de OpenAI. Obligatorio con `LLM_PROVIDER=openai`. |
| `LLM_TIMEOUT_SECONDS` | `30` | Timeout de cada llamada al LLM (504 si se agota). |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://jaeger:4317` | Destino OTLP gRPC de las trazas. |
| `LOG_LEVEL` | `INFO` | Nivel de los logs. |

Otras variables que acepta el backend con su valor por defecto, sin necesidad de definirlas: `OTEL_ENABLED` (`true`), `OTEL_SERVICE_NAME` (el compose la fija a `clausulia-api` y `clausulia-worker`), `EMBEDDING_BATCH_SIZE` (`32`), `DEFAULT_ORG_ID` (`default`), `STUCK_AFTER_MINUTES` (`10`, minutos en `pending` o `processing` para considerar atascado un documento) y `MAX_INGEST_ATTEMPTS` (`5`, intentos antes de marcarlo `failed` con `STUCK`). `TEST_DATABASE_URL` solo la usan los tests y la evaluación.

## Activar OpenAI

En el `.env` de la raíz:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=<tu clave>
OPENAI_MODEL=<un modelo con Responses API y Structured Outputs>
```

y recrea la API para que lea el nuevo `.env`: `docker compose up -d --force-recreate api`.

El proveedor usa el SDK oficial con la Responses API y Structured Outputs en modo estricto (`store=False`), un timeout de `LLM_TIMEOUT_SECONDS` y hasta 3 reintentos con backoff ante 429 y 5xx, respetando `Retry-After` (con un máximo de 30 s). Los errores se traducen a 429, 502 y 504. nginx da a `/api/ask` un timeout de 120 s para cubrir el timeout del LLM más los reintentos.

**Está probado con dobles del cliente de OpenAI, no contra la API real**: los tests cubren la petición, la lectura de la respuesta y los tokens, los reintentos y el mapeo de errores, pero nadie lo ha ejecutado con una clave.

## Tests

### Backend

Requiere uv (instala Python 3.12 si hace falta). Los tests de integración usan un Postgres real: con el compose levantado, crea una vez la base de pruebas:

```bash
docker compose exec postgres createdb -U clausulia clausulia_test
```

Crea `backend/.env` (solo para desarrollo local; está en `.gitignore`):

```env
DATABASE_URL=postgresql+psycopg://clausulia:clausulia@localhost:55432/clausulia
REDIS_URL=redis://localhost:6380/0
TEST_DATABASE_URL=postgresql+psycopg://clausulia:clausulia@localhost:55432/clausulia_test
EMBEDDING_CACHE_DIR=./.models
```

Y desde `backend/`:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -v
```

Los tests de integración aplican las migraciones sobre `clausulia_test` y vacían sus tablas. Si `TEST_DATABASE_URL` no está definida, se saltan (en CI fallan). Ningún test necesita red ni Redis: usan un embedder falso y el LLM simulado. El test que descarga el modelo real está marcado `model` y excluido por defecto (`uv run pytest -m model` para ejecutarlo).

Qué cubren:

- **Unitarios:** chunking, extracción de PDF (inválido, cifrado, demasiadas páginas, sin texto), embeddings, backoff de las tareas, esquemas y prompts (incluido el escape de etiquetas inyectadas), proveedor simulado, proveedor OpenAI con dobles, orquestación de la respuesta (umbral, reintento ante JSON inválido, citas inventadas descartadas, confianza, conflicto), mensajes de validación de la API y telemetría.
- **Integración:** ingesta y recuperación de atascados, endpoints de documentos, preguntas y salud (incluidos aislamiento por organización, duplicados y códigos de error), búsqueda vectorial e híbrida, migraciones (upgrade sobre datos existentes y downgrade) y trazas de punta a punta.

### Frontend

Requiere Node 22 y pnpm (la versión está fijada en `packageManager`; con `corepack enable` se usa la correcta). Desde `frontend/`:

```bash
pnpm install
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

Los tests (Vitest + Testing Library) cubren la validación de archivos antes de subir, el polling mientras haya documentos en curso, la traducción de códigos de error y los componentes de estado, subida, citas y respuesta (confianza, conflicto, sin evidencia, error con `trace_id`).

### CI

`.github/workflows/ci.yml` ejecuta en cada push y pull request los pasos anteriores del backend (con Postgres pgvector y Redis como servicios), los del frontend y gitleaks sobre todo el historial.

### Evaluación de la recuperación

Mide la recuperación sin LLM sobre `samples/` con las 20 preguntas de `backend/eval/questions.yaml` (16 con respuesta y 4 sin ella), usando el modelo real de embeddings. Usa `TEST_DATABASE_URL` y **vacía sus tablas**. Desde `backend/`:

```bash
uv run python -m eval.run_eval
```

Compara modo vector e híbrido, chunk de 500 y 1000, k de 4 y 6, cuatro umbrales y la cabecera con el título del documento. Calcula hit rate@k, MRR, tasa de rechazo correcto, falsos rechazos y latencia, y escribe los resultados, la configuración elegida y sus limitaciones en [backend/eval/results.md](backend/eval/results.md).

Para regenerar los PDF de ejemplo (el resultado es idéntico byte a byte): `uv run python scripts/generate_samples.py`.

## Qué está hecho

- Subida de PDFs con validación (tamaño, `%PDF-`, cifrados, número de páginas), deduplicación por SHA-256 dentro de cada organización y reencolado de los que fallaron.
- Ingesta en segundo plano con Celery: reintentos con backoff solo ante errores transitorios (base de datos, red, carga del modelo de embeddings), escritura atómica de los chunks y rescate periódico de documentos atascados.
- Búsqueda híbrida (pgvector HNSW + full-text en español) con Reciprocal Rank Fusion, filtrada siempre por organización.
- Respuestas con citas a documento y página, validadas: citas a fragmentos no recuperados se descartan, JSON inválido tiene un reintento y luego `rejected`, y sin evidencia no se llama al LLM.
- Confianza calculada como la menor entre la del LLM y la que justifica la similitud; conflicto solo si las citas vienen de dos documentos distintos.
- Defensa frente a prompt injection: fragmentos delimitados y escapados, y el system prompt los declara como datos.
- Errores HTTP con formato único `{"error": {"code", "message", "trace_id"}}`.
- Trazas OpenTelemetry de punta a punta (API, worker, SQL, Redis) y logs JSON con `trace_id`.
- Interfaz React con subida múltiple, estado en vivo, chat con citas y visor del fragmento citado.
- Evaluación reproducible de la recuperación y CI con lint, tipos, tests y detección de secretos.

## Qué no está hecho y limitaciones conocidas

- **Sin autenticación.** La organización llega en el header `X-Org-Id` y se confía en él: el aislamiento está en el modelo de datos y en todas las consultas, pero no es seguridad real. Flower tampoco tiene contraseña.
- **Sin OCR.** Los PDF escaneados se rechazan con `NO_TEXT_LAYER`.
- **Sin `unaccent`.** La búsqueda full-text no iguala palabras con y sin tilde («penalizacion» no coincide con «penalización»).
- **Evaluación pequeña.** 20 preguntas sobre 5 contratos sintéticos. El umbral de 0.50 separa este conjunto con un margen de solo 0.02 entre preguntas con y sin respuesta; con documentos reales habrá preguntas a ambos lados. Dos preguntas fallan con la configuración elegida (ver `backend/eval/results.md`): una del conflicto de preaviso formulada sin decir «preaviso» y otra que exige asociar una cláusula al proveedor nombrado solo en el encabezado.
- **OpenAI no probado contra la API real**, solo con dobles del cliente.
- **El proveedor simulado no detecta conflictos** ni entiende la pregunta: sirve para probar el flujo, no la calidad de las respuestas.
- **Sin paginación.** `GET /documents` devuelve todos los documentos de la organización.
- **Sin borrado de documentos** ni reprocesado manual desde la API.
- **Sin memoria de conversación.** Cada pregunta es independiente.
- **La interfaz no permite elegir organización ni filtrar por documentos**, aunque `POST /ask` acepta `document_ids`.
- **Solo trazas.** No hay métricas OpenTelemetry; las latencias van como atributos `*.duration_ms` de los spans. Jaeger guarda en memoria.
- **Beat embebido en el worker.** Si se escala a varios workers habría que sacarlo a su propio proceso para no duplicar el barrido.

## Problemas comunes

**Un puerto ya está ocupado** (`Bind for 0.0.0.0:3000 failed: port is already allocated` o similar). Cambia el puerto del host, el número de la izquierda, en `docker-compose.yml`. Por ejemplo, para la interfaz:

```yaml
  frontend:
    ports:
      - "3001:80"   # antes "3000:80"
```

Lo mismo para `api` (`8000:8000`), `postgres` (`55432:5432`), `redis` (`6380:6379`), `jaeger` (`16686`, `4317`, `4318`) y `flower` (`5555:5555`). Los servicios se comunican entre sí por la red de Docker con sus puertos internos, así que no hay que tocar nada más; solo cambian las URLs desde tu máquina (y `backend/.env` si cambias Postgres o Redis y ejecutas los tests en local).

**El primer documento se queda mucho tiempo en `pending`.** Es la descarga del modelo de embeddings, unos 240 MB. Se puede seguir con `docker compose logs -f worker`. Si la descarga falla (por ejemplo, sin conexión), la tarea se reintenta hasta 5 veces con backoff exponencial (1, 2, 4, 8 y 16 s, más jitter) y después el documento queda `failed` con el código `EMBEDDINGS_UNAVAILABLE`. Cuando vuelva la conexión, sube de nuevo el mismo PDF: al estar `failed`, se reencola. Una vez descargado, el modelo queda en el volumen `models` y no se vuelve a descargar salvo con `docker compose down -v`.

**Un documento se queda en `pending`.** El worker no está corriendo o no llega a Redis: revisa `docker compose ps` y `docker compose logs worker`. Al volver el worker, la tarea encolada se procesa; si se perdió, el barrido periódico lo reencola pasados 10 minutos.

**La API responde 503.** Postgres o Redis no responden: `http://localhost:8000/health` indica cuál.

## Estructura del repositorio

```
.
├── docker-compose.yml        # todos los servicios
├── .env.example              # copiar a .env
├── DECISIONS.md              # decisiones de diseño y su porqué
├── samples/                  # PDF de ejemplo generados
├── docs/                     # capturas de la interfaz y de Jaeger
├── .github/workflows/ci.yml  # CI
├── backend/
│   ├── Dockerfile            # imagen única: api, worker, flower y migrate
│   ├── pyproject.toml, uv.lock
│   ├── alembic.ini
│   ├── migrations/           # esquema (Alembic)
│   ├── app/
│   │   ├── main.py           # FastAPI y manejo de errores
│   │   ├── api/              # endpoints, dependencias y formato de errores
│   │   ├── core/             # configuración, logging y telemetría
│   │   ├── db/               # modelos y sesión
│   │   ├── ingestion/        # extracción, chunking, embeddings, almacenamiento, ingesta y rescate
│   │   ├── retrieval/        # búsqueda vectorial e híbrida
│   │   ├── llm/              # interfaz, proveedor simulado, OpenAI y prompts
│   │   ├── rag/              # orquestación de la respuesta
│   │   ├── schemas/          # modelos Pydantic de la API y del LLM
│   │   └── worker/           # Celery: configuración y tareas
│   ├── tests/                # unit/ e integration/
│   ├── scripts/generate_samples.py
│   └── eval/                 # questions.yaml, run_eval.py y results.md
└── frontend/
    ├── Dockerfile, nginx.conf
    ├── package.json, pnpm-lock.yaml
    └── src/                  # React + TanStack Query, componentes y tests
```
