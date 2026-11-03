"""División del texto de un PDF en fragmentos (chunks) con su número de página.

Reglas:
- Ningún chunk cruza de una página a otra: así cada cita apunta a una sola página.
- Ningún chunk supera `chunk_size` caracteres.
- Se corta por párrafos, luego por oraciones y, solo si no queda otra, por palabras.
- Cada chunk empieza con las últimas palabras del anterior (solapamiento).
"""

import re
from dataclasses import dataclass

_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_SPACES = re.compile(r"[ \t\f\v]+")
_MANY_NEWLINES = re.compile(r"\n{3,}")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.;:!?])\s+")


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    page_number: int
    content: str


def normalize_text(text: str) -> str:
    """Limpia el texto extraído de un PDF sin cambiar su contenido."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _MANY_NEWLINES.sub("\n\n", text)
    return text.strip()


def chunk_pages(pages: list[PageText], chunk_size: int, chunk_overlap: int) -> list[TextChunk]:
    """Divide cada página en chunks. Los índices son consecutivos en todo el documento."""
    if chunk_size <= 0:
        raise ValueError("chunk_size debe ser positivo")
    if not 0 <= chunk_overlap < chunk_size:
        raise ValueError("chunk_overlap debe estar entre 0 y chunk_size - 1")

    chunks: list[TextChunk] = []
    for page in pages:
        for content in _chunk_text(normalize_text(page.text), chunk_size, chunk_overlap):
            chunks.append(TextChunk(len(chunks), page.page_number, content))
    return chunks


def _chunk_text(text: str, size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for segment in _split_segments(text, size):
        candidate = f"{current}\n{segment}" if current else segment
        if len(candidate) <= size:
            current = candidate
            continue
        # El segmento no cabe: se cierra el chunk actual y se abre otro.
        if current:
            chunks.append(current)
        tail = _tail(current, overlap)
        with_overlap = f"{tail} {segment}"
        current = with_overlap if tail and len(with_overlap) <= size else segment
    if current:
        chunks.append(current)
    return chunks


def _split_segments(text: str, size: int) -> list[str]:
    """Párrafos; si un párrafo no cabe, oraciones; si una oración no cabe, palabras."""
    segments: list[str] = []
    for paragraph in _PARAGRAPH_BREAK.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= size:
            segments.append(paragraph)
            continue
        for sentence in _SENTENCE_END.split(paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) <= size:
                segments.append(sentence)
            else:
                segments.extend(_split_words(sentence, size))
    return segments


def _split_words(text: str, size: int) -> list[str]:
    """Último recurso: corta por palabras; una palabra gigante se corta por caracteres."""
    parts: list[str] = []
    current = ""
    for word in text.split():
        while len(word) > size:
            if current:
                parts.append(current)
                current = ""
            parts.append(word[:size])
            word = word[size:]
        candidate = f"{current} {word}" if current else word
        if len(candidate) <= size:
            current = candidate
        else:
            parts.append(current)
            current = word
    if current:
        parts.append(current)
    return parts


def _tail(text: str, overlap: int) -> str:
    """Últimos `overlap` caracteres de `text`, empezando en una palabra completa."""
    if overlap == 0 or not text:
        return ""
    if len(text) <= overlap:
        return text
    tail = text[-overlap:]
    first_space = tail.find(" ")
    return tail[first_space + 1 :] if first_space != -1 else tail
