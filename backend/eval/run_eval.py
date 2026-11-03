"""Evaluación de la recuperación (sin LLM) sobre los contratos de samples/. Uso, desde backend/:

    uv run python -m eval.run_eval

Usa TEST_DATABASE_URL (vacía sus tablas) y el modelo real de embeddings. Por cada chunk_size
y cada valor de la cabecera con el título del documento, limpia las tablas e ingiere los PDF
con run_ingestion; después ejecuta search_chunks para cada combinación de modo, k y umbral.
Imprime el informe y lo guarda en eval/results.md. La configuración "elegida" es la de los
valores por defecto de Settings.
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
TITLES = (False, True)  # EMBED_DOCUMENT_TITLE


@dataclass(frozen=True)
class Question:
    id: str
    kind: str
    text: str
    expected: list[tuple[str, int]]  # (archivo, página); vacío = sin respuesta


@dataclass(frozen=True)
class Setup:
    mode: RetrievalMode
    chunk_size: int
    overlap: int
    k: int
    threshold: float
    title: bool


@dataclass(frozen=True)
class QuestionResult:
    rank: int | None  # posición del primer acierto entre los k
    hit_similarity: float | None  # similitud de ese chunk
    best_similarity: float  # similitud del mejor chunk recuperado
    rejected: bool  # el mejor no llega al umbral: no se llamaría al LLM


@dataclass(frozen=True)
class Metrics:
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
                f"{document.chunk_count} chunks"
                if document.status == DocumentStatus.READY
                else f"{document.status.value} ({document.error_code})"
            )
    return statuses


def evaluate(
    session_factory: sessionmaker[Session],
    embedder: Embedder,
    questions: list[Question],
    settings: Settings,
    setup: Setup,
) -> tuple[Metrics, dict[str, QuestionResult]]:
    def search(session: Session, question: str) -> RetrievalResult:
        return search_chunks(
            session,
            embedder,
            question,
            ORG,
            k=setup.k,
            threshold=setup.threshold,
            mode=setup.mode,
            candidates=settings.hybrid_candidates,
            rrf_k=settings.rrf_k,
        )

    with session_factory() as session:
        search(session, questions[0].text)  # calentamiento: caché de Postgres y conexión

    results: dict[str, QuestionResult] = {}
    latencies = []
    for q in questions:
        with session_factory() as session:
            start = time.perf_counter()
            retrieval = search(session, q.text)
            latencies.append((time.perf_counter() - start) * 1000)
        rank = next(
            (
                i
                for i, c in enumerate(retrieval.chunks, start=1)
                if (c.document_name, c.page_number) in q.expected
            ),
            None,
        )
        results[q.id] = QuestionResult(
            rank=rank,
            hit_similarity=retrieval.chunks[rank - 1].similarity if rank else None,
            best_similarity=retrieval.best_similarity or 0.0,
            rejected=not retrieval.has_evidence,
        )

    answerable = [results[q.id] for q in questions if q.expected]
    unanswerable = [results[q.id] for q in questions if not q.expected]
    metrics = Metrics(
        hit_rate=sum(r.rank is not None for r in answerable) / len(answerable),
        mrr=statistics.mean(1 / r.rank if r.rank else 0.0 for r in answerable),
        useful_hit_rate=sum(r.rank is not None and not r.rejected for r in answerable)
        / len(answerable),
        correct_rejection=sum(r.rejected for r in unanswerable) / len(unanswerable),
        false_rejection=sum(r.rejected for r in answerable) / len(answerable),
        latency_ms=statistics.mean(latencies),
    )
    return metrics, results


def _row(setup: Setup, m: Metrics) -> str:
    return (
        f"| {setup.mode} | {setup.chunk_size} | {setup.overlap} | {setup.k} "
        f"| {setup.threshold:.2f} | {'sí' if setup.title else 'no'} | {m.hit_rate:.0%} "
        f"| {m.mrr:.3f} | {m.useful_hit_rate:.0%} | {m.correct_rejection:.0%} "
        f"| {m.false_rejection:.0%} | {m.latency_ms:.1f} |"
    )


def _title_verdict(chosen: Setup, chosen_metrics: Metrics, other: Metrics) -> str:
    """Criterio: la cabecera se activa si mejora hit@k o MRR sin empeorar el rechazo."""
    on, off = (chosen_metrics, other) if chosen.title else (other, chosen_metrics)
    improves = on.hit_rate > off.hit_rate or on.mrr > off.mrr
    keeps_rejection = on.correct_rejection >= off.correct_rejection
    verdict = "conviene activarla" if improves and keeps_rejection else "se deja desactivada"
    return (
        f"Cabecera con el título del documento: hit@k {off.hit_rate:.0%} → {on.hit_rate:.0%}, "
        f"MRR {off.mrr:.3f} → {on.mrr:.3f}, rechazo correcto {off.correct_rejection:.0%} → "
        f"{on.correct_rejection:.0%}. Criterio: activarla solo si mejora hit@k o MRR sin "
        f"empeorar el rechazo correcto; {verdict}."
    )


TABLE_HEADER = [
    "| modo | chunk | overlap | k | umbral | título | hit@k | MRR | útil@k | rechazo correcto "
    "| falso rechazo | latencia (ms) |",
    "|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|",
]


def render(
    runs: dict[Setup, tuple[Metrics, dict[str, QuestionResult]]],
    chosen: Setup,
    questions: list[Question],
    statuses: dict[tuple[int, bool], dict[str, str]],
    model: str,
    embed_ms: float,
    settings: Settings,
) -> str:
    chosen_metrics, chosen_results = runs[chosen]
    answerable = [chosen_results[q.id] for q in questions if q.expected]
    unanswerable = [chosen_results[q.id] for q in questions if not q.expected]
    gap = min(r.best_similarity for r in answerable) - max(r.best_similarity for r in unanswerable)
    misses = [q.id for q in questions if q.expected and chosen_results[q.id].rank is None]
    without_title = runs[Setup(**{**chosen.__dict__, "title": not chosen.title})][0]

    lines = [
        "# Evaluación de la recuperación",
        "",
        f"- Fecha: {datetime.now(UTC):%Y-%m-%d %H:%M} UTC",
        f"- Modelo de embeddings: `{model}` (384 dimensiones, fastembed/ONNX, CPU)",
        f"- Preguntas: {len(questions)} ({len(answerable)} con respuesta, "
        f"{len(unanswerable)} sin respuesta), en `eval/questions.yaml`",
        f"- Documentos: `samples/` (5 contratos con texto y 1 escaneado); hybrid con "
        f"{settings.hybrid_candidates} candidatos por rama y RRF k={settings.rrf_k}",
        f"- Overlap: {OVERLAP_RATIO:.0%} del chunk_size",
        f"- Vectorizar una pregunta (no incluido en la latencia): {embed_ms:.1f} ms de media",
        "",
        "Métricas:",
        "",
        "- hit@k: el archivo y la página esperados están entre los k chunks recuperados.",
        "- MRR: media de 1/posición del primer acierto (0 si no está entre los k).",
        "- útil@k: hay acierto y además el mejor chunk pasa el umbral, así que el LLM lo "
        "recibiría.",
        "- rechazo correcto: preguntas sin respuesta cuyo mejor chunk no llega al umbral "
        "(no se llama al LLM).",
        "- falso rechazo: preguntas con respuesta cuyo mejor chunk no llega al umbral.",
        "- título: cabecera `Documento: <nombre>` antepuesta al vectorizar (EMBED_DOCUMENT_TITLE).",
        "- latencia: búsqueda en Postgres, sin vectorizar la pregunta.",
        "",
        "## Configuración elegida",
        "",
        f"RETRIEVAL_MODE={chosen.mode}, CHUNK_SIZE={chosen.chunk_size}, "
        f"CHUNK_OVERLAP={chosen.overlap}, RETRIEVAL_K={chosen.k}, "
        f"SIMILARITY_THRESHOLD={chosen.threshold:.2f}, "
        f"EMBED_DOCUMENT_TITLE={'true' if chosen.title else 'false'}. El umbral solo decide "
        "si se llama al LLM (con la similitud del mejor chunk); si se llama, recibe los k.",
        "",
        *TABLE_HEADER,
        _row(chosen, chosen_metrics),
        _row(Setup(**{**chosen.__dict__, "title": not chosen.title}), without_title),
        "",
        f"Separación con esta configuración: el peor «mejor chunk» de una pregunta con "
        f"respuesta menos el mejor de una sin respuesta = {gap:+.2f}.",
        "",
        _title_verdict(chosen, chosen_metrics, without_title),
        "",
        "## Ingesta",
        "",
    ]
    for (size, title), by_file in statuses.items():
        files = ", ".join(f"{f}: {s}" for f, s in by_file.items())
        lines.append(f"- chunk_size {size}, título {'sí' if title else 'no'}: {files}")
    lines += ["", "## Resultados completos", "", *TABLE_HEADER]
    lines += [_row(setup, metrics) for setup, (metrics, _) in runs.items()]

    detail_setups = [
        s
        for s in runs
        if s.chunk_size == chosen.chunk_size and s.k == chosen.k and s.threshold == chosen.threshold
    ]
    lines += [
        "",
        f"## Detalle por pregunta (chunk {chosen.chunk_size}, k={chosen.k})",
        "",
        "Posición del primer acierto (– si no está entre los k), similitud coseno de ese chunk "
        "y, entre corchetes, la del mejor chunk recuperado.",
        "",
        "| pregunta | tipo | "
        + " | ".join(f"{s.mode}{' + título' if s.title else ''}" for s in detail_setups)
        + " |",
        "|---|---|" + "---:|" * len(detail_setups),
    ]
    for q in questions:
        cells = []
        for s in detail_setups:
            r = runs[s][1][q.id]
            found = f"{r.rank} ({r.hit_similarity:.2f})" if r.rank and r.hit_similarity else "–"
            cells.append(f"{found} [{r.best_similarity:.2f}]")
        lines.append(f"| {q.id} {q.text} | {q.kind} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## Limitaciones",
        "",
        f"- Conjunto pequeño: {len(questions)} preguntas sobre 5 contratos sintéticos y "
        f"redactados para la prueba. Una pregunta equivale a {1 / len(answerable):.0%} de "
        "hit@k: diferencias de una o dos preguntas entre configuraciones son ruido.",
        f"- Separación de {gap:+.2f} entre preguntas con y sin respuesta. El umbral "
        f"{chosen.threshold:.2f} separa este conjunto, pero con documentos reales habrá "
        "preguntas a ambos lados: el LLM sigue siendo el segundo filtro (puede responder "
        "insufficient_evidence y las citas se validan).",
        "- Las preguntas sin respuesta son del mismo dominio (seguros, horarios, tarifas): "
        "son las difíciles. No se midieron preguntas ajenas a los contratos.",
        f"- Preguntas que no encuentran su página con la configuración elegida: "
        f"{', '.join(misses) or 'ninguna'}. q03 (preaviso de Suministros Andinos, la del "
        "conflicto entre dos contratos) sufre en hybrid: el nombre del proveedor aparece en "
        "los encabezados y esos chunks suben por full-text. q11 (vigencia del contrato con "
        "Peñalara) necesita asociar la cláusula al proveedor, que solo se nombra en el "
        "encabezado.",
        "- Sin `unaccent`: el full-text con la configuración `spanish` no iguala palabras con "
        "y sin tilde («penalizacion» no coincide con «penalización»). Añadirlo exige la "
        "extensión y una función inmutable para la columna generada.",
        "- El full-text une los términos con OR y `ts_rank_cd` no pondera por rareza (no hay "
        "IDF): palabras comunes como «contrato» o «fecha» pesan tanto como un nombre propio.",
        "- La latencia se midió con unas pocas decenas de chunks; no dice nada de miles.",
    ]
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

    # Solo se fijan la base y el proveedor: el resto son los valores por defecto (los elegidos).
    base = Settings(database_url=url, redis_url="redis://unused", embedding_provider="fastembed")
    chosen = Setup(
        base.retrieval_mode,
        base.chunk_size,
        base.chunk_overlap,
        base.retrieval_k,
        base.similarity_threshold,
        base.embed_document_title,
    )
    print(f"Cargando {base.embedding_model}...")
    model = FastEmbedEmbedder(
        base.embedding_model, base.embedding_cache_dir, base.embedding_batch_size
    )
    start = time.perf_counter()
    for q in questions:
        model.embed_query(q.text)
    embed_ms = (time.perf_counter() - start) * 1000 / len(questions)
    embedder = CachedQueryEmbedder(model)

    runs: dict[Setup, tuple[Metrics, dict[str, QuestionResult]]] = {}
    statuses: dict[tuple[int, bool], dict[str, str]] = {}
    with tempfile.TemporaryDirectory() as upload_dir:
        for size in CHUNK_SIZES:
            overlap = round(size * OVERLAP_RATIO)
            for title in TITLES:
                settings = base.model_copy(
                    update={
                        "chunk_size": size,
                        "chunk_overlap": overlap,
                        "upload_dir": upload_dir,
                        "embed_document_title": title,
                    }
                )
                print(f"Ingiriendo con chunk_size={size}, overlap={overlap}, título={title}...")
                statuses[(size, title)] = ingest_samples(session_factory, settings, embedder)
                for mode in MODES:
                    for k in KS:
                        for threshold in THRESHOLDS:
                            setup = Setup(mode, size, overlap, k, threshold, title)
                            runs[setup] = evaluate(
                                session_factory, embedder, questions, settings, setup
                            )
    engine.dispose()

    if chosen not in runs:
        print(f"La configuración por defecto {chosen} no está en la rejilla", file=sys.stderr)
        return 1
    report = render(runs, chosen, questions, statuses, model.name, embed_ms, base)
    (EVAL_DIR / "results.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"Guardado en {EVAL_DIR / 'results.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
