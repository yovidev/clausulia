from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from app.ingestion.extraction import PdfExtractionError, PypdfExtractor

extractor = PypdfExtractor()


def _make_pdf(path: Path, pages: list[str]) -> Path:
    pdf = canvas.Canvas(str(path))
    for text in pages:
        if text:
            pdf.drawString(72, 720, text)
        pdf.showPage()
    pdf.save()
    return path


def test_extracts_text_per_page(tmp_path: Path) -> None:
    pdf = _make_pdf(
        tmp_path / "ok.pdf",
        [
            "El contrato se renueva automaticamente cada doce meses.",
            "La jurisdiccion aplicable es la de los tribunales de Madrid.",
        ],
    )
    pages = extractor.extract(pdf, max_pages=10)
    assert [p.page_number for p in pages] == [1, 2]
    assert "renueva" in pages[0].text
    assert "Madrid" in pages[1].text


def test_scanned_pdf_without_text_is_rejected(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "scan.pdf", ["", ""])
    with pytest.raises(PdfExtractionError) as exc:
        extractor.extract(pdf, max_pages=10)
    assert exc.value.code == "NO_TEXT_LAYER"


def test_corrupt_file_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.7\nesto no es un pdf de verdad")
    with pytest.raises(PdfExtractionError) as exc:
        extractor.extract(bad, max_pages=10)
    assert exc.value.code == "INVALID_PDF"


def test_too_many_pages_is_rejected(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "long.pdf", ["Pagina uno con texto.", "Pagina dos con texto."])
    with pytest.raises(PdfExtractionError) as exc:
        extractor.extract(pdf, max_pages=1)
    assert exc.value.code == "TOO_MANY_PAGES"


def test_password_protected_pdf_is_rejected(tmp_path: Path) -> None:
    plain = _make_pdf(tmp_path / "plain.pdf", ["Contenido confidencial del contrato."])
    writer = PdfWriter()
    for page in PdfReader(plain).pages:
        writer.add_page(page)
    writer.encrypt(user_password="secreto", algorithm="RC4-128")  # noqa: S106  contraseña de prueba
    locked = tmp_path / "locked.pdf"
    with locked.open("wb") as f:
        writer.write(f)

    with pytest.raises(PdfExtractionError) as exc:
        extractor.extract(locked, max_pages=10)
    assert exc.value.code == "ENCRYPTED_PDF"
    
    
def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        extractor.extract(tmp_path / "no-existe.pdf", max_pages=10)
