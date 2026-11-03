"""Ubicación de los PDF subidos. Se guardan por su hash, nunca por el nombre original."""

import re
from pathlib import Path

_SHA256 = re.compile(r"[0-9a-f]{64}")


def upload_path(upload_dir: str, sha256: str) -> Path:
    # Validar el hash impide construir rutas como "../../etc/passwd".
    if not _SHA256.fullmatch(sha256):
        raise ValueError("Hash SHA-256 inválido")
    return Path(upload_dir) / f"{sha256}.pdf"
