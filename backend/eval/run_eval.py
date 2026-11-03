"""Evaluación de la recuperación (sin LLM) sobre los contratos de samples/. Uso, desde backend/:

    uv run python -m eval.run_eval

Usa TEST_DATABASE_URL (vacía sus tablas) y el modelo real de embeddings. Por cada
chunk_size limpia las tablas e ingiere los PDF con run_ingestion; después ejecuta
search_chunks para cada combinación de modo, k y umbral. Imprime la tabla y la guarda en
eval/results.md.
"""

import hashlib
import os
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db.models import Document, DocumentStatus
from app.ingestion.embeddings import Embedder, FastEmbedEmbedder
from app.ingestion.extraction import PypdfExtractor
from app.ingestion.service import run_ingestion
from app.retrieval.search import RetrievalMode, RetrievalResult, search_chunks

EVAL_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = EVAL_DIR.parents[1] / "samples"
ORG = "eval"

MODES: tuple[RetrievalMode, ...] = ("vector", "hybrid")
CHUNK_SIZES = (500, 1000)
OVERLAP_RATIO = 0.15  # 150 para 1000, 75 para 500
KS = (4, 6)
THRESHOLDS = (0.35, 0.45, 0.50, 0.55)
# Margen de umbral para chunks que coinciden por palabras (solo hybrid; 0 = sin ventaja).
MARGINS = (0.0, 0.05, 0.10)

# Por pregunta: posición del primer acierto, similitud de ese chunk y del mejor recuperado.
Detail = tuple[int | None, float | None, float]


@dataclass(frozen=True)
class Question:
    id: str
    kind: str
    text: str
    expected: list[tuple[str, int]]  # (archivo, página)


@dataclass(frozen=True)
class Row:
    mode: str
    chunk_size: int
    overlap: int
    k: int
    threshold: float
    margin: float | None  # None en modo vector
    hit_rate: float
    mrr: float
    useful_hit_rate: float
    correct_rejection: float
    false_rejection: float
    latency_ms: float


class CachedQueryEmbedder:
    """Vectoriza cada pregunta una sola vez: la latencia medida es solo la de la búsqueda."""

    def __init__(self, inner: Embedder) -> None:
        self._inner = inner
        self.name = inner.name
        self._cache: dict[str, list[float]] = {}

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._inner.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        if text not in self._cache:
            self._cache[text] = self._inner.embed_query(text)
        return self._cache[text]


def load_questions() -> list[Question]:
    data = yaml.safe_load((EVAL_DIR / "questions.yaml").read_text(encoding="utf-8"))
    return [
        Question(
            id=q["id"],
            kind=q["kind"],
            text=q["question"],
            expected=[(e["file"], e["page"]) for e in q["expected"]],
        )
        for q in data["questions"]
    ]


def check_evidence() -> list[str]:
    """Comprueba que cada evidencia está en la página anotada. Devuelve los errores."""
    data = yaml.safe_load((EVAL_DIR / "questions.yaml").read_text(encoding="utf-8"))
    extractor = PypdfExtractor()
    pages: dict[str, list[str]] = {}
    errors = []
    for q in data["questions"]:
        for e in q["expected"]:
            if e["file"] not in pages:
                extracted = extractor.extract(SAMPLES_DIR / e["file"], 500)
                pages[e["file"]] = [" ".join(p.text.split()) for p in extracted]
            if e["evidence"] not in pages[e["file"]][e["page"] - 1]:
                errors.append(f"{q['id']}: «{e['evidence']}» no está en {e['file']} p.{e['page']}")
    return errors


def ingest_samples(
    session_factory: sessionmaker[Session], settings: Settings, embedder: Embedder
) -> dict[str, str]:
    """Vacía las tablas e ingiere todos los PDF. Devuelve el estado final de cada archivo."""
    with session_factory() as session, session.begin():
        session.execute(text("TRUNCATE chunks, documents CASCADE"))
    statuses = {}
    for path in sorted(SAMPLES_DIR.glob("*.pdf")):
        data = path.read_bytes()
        sha256 = hashlib.sha256(data).hexdigest()
        (Path(settings.upload_dir) / f"{sha256}.pdf").write_bytes(data)
        with session_factory() as session, session.begin():
            document = Document(
                organization_id=ORG, filename=path.name, sha256=sha256, size_bytes=len(data)
            )
            session.add(document)
            session.flush()
            document_id = document.id
        run_ingestion(
            document_id,
            session_factory=session_factory,
            extractor=PypdfExtractor(),
            embedder=embedder,
            settings=settings,
        )
        with session_factory() as session:
            document = session.get_one(Document, document_id)
            statuses[path.name] = (
                f"{document.status.value} ({document.chunk_count} chunks)"
                if document.status == DocumentStatus.READY
                else f"{document.status.value} ({document.error_code})"
            )
    return statuses


def first_hit_rank(result: RetrievalResult, expected: list[tuple[str, int]]) -> int | None:
    for rank, chunk in enumerate(result.chunks, start=1):
        if (chunk.document_name, chunk.page_number) in expected:
            return rank
    return None


def evaluate(
    session_factory: sessionmaker[Session],
    embedder: Embedder,
    questions: list[Question],
    settings: Settings,
    mode: RetrievalMode,
    k: int,
    threshold: float,
    margin: float,
) -> tuple[dict[str, float], dict[str, Detail]]:
    """Métricas de una configuración y el detalle por pregunta."""

    def search(session: Session, question: str) -> RetrievalResult:
        return search_chunks(
            session,
            embedder,
            question,
            ORG,
            k=k,
            threshold=threshold,
            mode=mode,
            candidates=settings.hybrid_candidates,
            rrf_k=settings.rrf_k,
            text_margin=margin,
        )

    with session_factory() as session:
        search(session, questions[0].text)  # calentamiento: caché de Postgres y conexión

    answerable = [q for q in questions if q.expected]
    unanswerable = [q for q in questions if not q.expected]
    reciprocal, hits, useful, false_rej, correct_rej, latencies = [], 0, 0, 0, 0, []
    detail: dict[str, Detail] = {}
    for q in questions:
        with session_factory() as session:
            start = time.perf_counter()
            result = search(session, q.text)
            latencies.append((time.perf_counter() - start) * 1000)
        rejected = not result.relevant
        top = max((c.similarity for c in result.chunks), default=0.0)
        rank = first_hit_rank(result, q.expected) if q.expected else None
        detail[q.id] = (rank, result.chunks[rank - 1].similarity if rank else None, top)
        if q.expected:
            hits += rank is not None
            reciprocal.append(1 / rank if rank else 0.0)
            useful += any((c.document_name, c.page_number) in q.expected for c in result.relevant)
            false_rej += rejected
        else:
            correct_rej += rejected
    metrics = {
        "hit_rate": hits / len(answerable),
        "mrr": statistics.mean(reciprocal),
        "useful_hit_rate": useful / len(answerable),
        "correct_rejection": correct_rej / len(unanswerable),
        "false_rejection": false_rej / len(answerable),
        "latency_ms": statistics.mean(latencies),
    }
    return metrics, detail


def render(
    rows: list[Row],
    details: dict[tuple[str, int], dict[str, Detail]],
    questions: list[Question],
    statuses: dict[int, dict[str, str]],
    model: str,
    embed_ms: float,
    settings: Settings,
) -> str:
    lines = [
        "# Evaluación de la recuperación",
        "",
        f"- Fecha: {datetime.now(UTC):%Y-%m-%d %H:%M} UTC",
        f"- Modelo de embeddings: `{model}` (384 dimensiones, fastembed/ONNX, CPU)",
        f"- Preguntas: {len(questions)} ({sum(1 for q in questions if q.expected)} con "
        f"respuesta, {sum(1 for q in questions if not q.expected)} sin respuesta)",
        f"- Hybrid: {settings.hybrid_candidates} candidatos por rama, RRF k={settings.rrf_k}",
        f"- Overlap: {OVERLAP_RATIO:.0%} del chunk_size",
        f"- Vectorizar una pregunta (no incluido en la latencia): {embed_ms:.1f} ms de media",
        "",
        "Métricas: hit@k = el archivo y la página esperados están entre los k primeros; "
        "MRR = media de 1/posición del primer acierto (0 si no está); útil@k = el acierto "
        "además pasa el umbral (es lo que llegaría al LLM); rechazo correcto = preguntas sin "
        "respuesta sin ningún chunk relevante; falso rechazo = preguntas con respuesta sin "
        "ningún chunk relevante; margen = rebaja del umbral para chunks que coinciden por "
        "palabras (solo hybrid); latencia = búsqueda en Postgres, sin vectorizar la pregunta.",
        "",
        "## Ingesta",
        "",
    ]
    for size, by_file in statuses.items():
        lines.append(f"- chunk_size {size}: " + ", ".join(f"{f} {s}" for f, s in by_file.items()))
    lines += [
        "",
        "## Resultados",
        "",
        "| modo | chunk | overlap | k | umbral | margen | hit@k | MRR | útil@k "
        "| rechazo correcto | falso rechazo | latencia (ms) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        margin = "–" if r.margin is None else f"{r.margin:.2f}"
        lines.append(
            f"| {r.mode} | {r.chunk_size} | {r.overlap} | {r.k} | {r.threshold:.2f} "
            f"| {margin} | {r.hit_rate:.0%} | {r.mrr:.3f} | {r.useful_hit_rate:.0%} "
            f"| {r.correct_rejection:.0%} | {r.false_rejection:.0%} | {r.latency_ms:.1f} |"
        )
    lines += [
        "",
        "## Detalle por pregunta (k=6)",
        "",
        "Posición del primer acierto (– si no está en los 6 primeros), similitud coseno de "
        "ese chunk y, entre corchetes, la del mejor chunk recuperado. No dependen del umbral.",
        "",
        "| pregunta | tipo | " + " | ".join(f"{m} {s}" for m, s in details) + " |",
        "|---|---|" + "---:|" * len(details),
    ]
    for q in questions:
        cells = []
        for detail in details.values():
            rank, hit, top = detail[q.id]
            found = f"{rank} ({hit:.2f})" if rank and hit is not None else "–"
            cells.append(f"{found} [{top:.2f}]")
        lines.append(f"| {q.id} {q.text} | {q.kind} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    load_dotenv(".env")
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        print("TEST_DATABASE_URL no está definida (backend/.env)", file=sys.stderr)
        return 1
    errors = check_evidence()
    if errors:
        print("Evidencias mal anotadas en questions.yaml:", *errors, sep="\n", file=sys.stderr)
        return 1

    # Alembic y Settings leen DATABASE_URL: se apunta a la base de pruebas.
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    engine = create_engine(url)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    questions = load_questions()

    base = Settings(database_url=url, redis_url="redis://unused", embedding_provider="fastembed")
    print(f"Cargando {base.embedding_model}...")
    model = FastEmbedEmbedder(
        base.embedding_model, base.embedding_cache_dir, base.embedding_batch_size
    )
    start = time.perf_counter()
    for q in questions:
        model.embed_query(q.text)
    embed_ms = (time.perf_counter() - start) * 1000 / len(questions)
    embedder = CachedQueryEmbedder(model)

    rows: list[Row] = []
    details: dict[tuple[str, int], dict[str, Detail]] = {}
    statuses: dict[int, dict[str, str]] = {}
    with tempfile.TemporaryDirectory() as upload_dir:
        for size in CHUNK_SIZES:
            overlap = round(size * OVERLAP_RATIO)
            settings = base.model_copy(
                update={"chunk_size": size, "chunk_overlap": overlap, "upload_dir": upload_dir}
            )
            print(f"Ingiriendo con chunk_size={size}, overlap={overlap}...")
            statuses[size] = ingest_samples(session_factory, settings, embedder)
            for mode in MODES:
                margins = MARGINS if mode == "hybrid" else (0.0,)
                for k in KS:
                    for threshold in THRESHOLDS:
                        for margin in margins:
                            metrics, detail = evaluate(
                                session_factory,
                                embedder,
                                questions,
                                settings,
                                mode,
                                k,
                                threshold,
                                margin,
                            )
                            shown = margin if mode == "hybrid" else None
                            rows.append(Row(mode, size, overlap, k, threshold, shown, **metrics))
                            if k == max(KS):
                                details[(mode, size)] = detail
    engine.dispose()

    report = render(rows, details, questions, statuses, model.name, embed_ms, base)
    (EVAL_DIR / "results.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"Guardado en {EVAL_DIR / 'results.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
