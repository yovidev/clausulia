from pathlib import Path

from reportlab.pdfgen import canvas


def make_pdf(path: Path, pages: list[str]) -> Path:
    """Crea un PDF con una línea de texto por página ("" = página sin texto)."""
    pdf = canvas.Canvas(str(path))
    for text in pages:
        if text:
            pdf.drawString(72, 720, text)
        pdf.showPage()
    pdf.save()
    return path
