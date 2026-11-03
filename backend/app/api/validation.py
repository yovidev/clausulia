"""Mensajes comprensibles para los errores de validación de FastAPI (422 VALIDATION_ERROR)."""

from collections.abc import Sequence
from typing import Any

INVALID_JSON = "El cuerpo de la petición no es JSON válido"
MAX_MESSAGES = 3

# Cómo se nombra cada campo en los mensajes (con artículo, para poder escribir "Falta ...").
_LABELS = {
    "question": "la pregunta",
    "document_ids": "la lista de documentos (document_ids)",
    "file": "el archivo (campo file)",
    "X-Org-Id": "el header X-Org-Id",
    "document_id": "el id del documento",
    "chunk_id": "el id del fragmento",
}


def validation_message(errors: Sequence[Any]) -> str:
    """Traduce los errores de Pydantic/FastAPI a una frase en español para el usuario."""
    if any(e.get("type") == "json_invalid" for e in errors):
        return INVALID_JSON
    messages = list(dict.fromkeys(_message(e) for e in errors))
    return ". ".join(messages[:MAX_MESSAGES])


def _message(error: dict[str, Any]) -> str:
    kind: str = error.get("type", "")
    loc: tuple[Any, ...] = tuple(error.get("loc", ()))
    ctx: dict[str, Any] = error.get("ctx") or {}
    names = [part for part in loc[1:] if isinstance(part, str)]
    is_item = any(isinstance(part, int) for part in loc[1:])

    if not names:  # el error es del cuerpo entero
        if kind == "missing":
            return "Falta el cuerpo de la petición"
        return "El cuerpo de la petición debe ser un objeto JSON"

    field = names[-1]
    label = _LABELS.get(field, f"el campo {field}")
    if kind == "missing":
        return _capitalize(f"falta {label}")
    if kind == "string_too_short":
        return _capitalize(f"{label} debe tener al menos {ctx.get('min_length')} caracteres")
    if kind == "string_too_long":
        return _capitalize(f"{label} debe tener como máximo {ctx.get('max_length')} caracteres")
    if kind == "too_short":
        return _capitalize(f"{label} debe tener al menos {ctx.get('min_length')} elemento(s)")
    if kind == "too_long":
        return _capitalize(f"{label} debe tener como máximo {ctx.get('max_length')} elementos")
    if kind in ("uuid_parsing", "uuid_type"):
        if is_item:
            return _capitalize(f"{label} contiene un id que no es un UUID válido")
        return _capitalize(f"{label} no es un UUID válido")
    if kind == "string_pattern_mismatch" and field == "X-Org-Id":
        return (
            "El header X-Org-Id solo admite letras, números, guiones y guiones bajos "
            "(de 1 a 64 caracteres)"
        )
    if kind == "string_type":
        return _capitalize(f"{label} debe ser texto")
    if kind == "list_type":
        return _capitalize(f"{label} debe ser una lista")
    return _capitalize(f"{label} no es válido")


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]
