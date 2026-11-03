"""Extracción del texto de un PDF, página por página.

Detrás de un Protocol para poder cambiar pypdf por otra herramienta (por ejemplo
Docling, si aparecen contratos con tablas complejas) sin tocar el resto del código.
"""

from pathlib import Path
from typing import Protocol

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.ingestion.chunking import PageText, normalize_text

# Por debajo de este promedio de caracteres por página, el PDF es un escaneo.
MIN_CHARS_PER_PAGE = 20


class PdfExtractionError(Exception):
    """Error permanente: reintentar no lo arregla."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PdfExtractor(Protocol):
    def extract(self, path: Path, max_pages: int) -> list[PageText]: ...


class PypdfExtractor:
    def extract(self, path: Path, max_pages: int) -> list[PageText]:
        try:
            reader = PdfReader(path)
        except (PdfReadError, ValueError, OSError) as exc:
            raise PdfExtractionError("INVALID_PDF", "El archivo no es un PDF válido") from exc

        # Algunos PDF están "cifrados" con contraseña vacía y se pueden leer igual.
        if reader.is_encrypted and not reader.decrypt(""):
            raise PdfExtractionError("ENCRYPTED_PDF", "El PDF está protegido con contraseña")

        try:
            page_count = len(reader.pages)
        except PdfReadError as exc:
            raise PdfExtractionError("INVALID_PDF", "No se pudieron leer las páginas") from exc

        if page_count == 0:
            raise PdfExtractionError("INVALID_PDF", "El PDF no tiene páginas")
        if page_count > max_pages:
            raise PdfExtractionError(
                "TOO_MANY_PAGES", f"El PDF tiene {page_count} páginas; el máximo es {max_pages}"
            )

        pages: list[PageText] = []
        for number, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001  pypdf puede fallar de muchas formas
                raise PdfExtractionError(
                    "INVALID_PDF", f"No se pudo leer la página {number}"
                ) from exc
            pages.append(PageText(number, text))

        total_chars = sum(len(normalize_text(p.text)) for p in pages)
        if total_chars / page_count < MIN_CHARS_PER_PAGE:
            raise PdfExtractionError(
                "NO_TEXT_LAYER",
                "El PDF no tiene texto extraíble; parece escaneado y no se hace OCR",
            )
        return pages
