"""Mensajes de 422 VALIDATION_ERROR: deben entenderse sin conocer FastAPI."""

import uuid
from collections.abc import Iterator

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.ingestion.embeddings import FakeEmbedder, get_embedder
from app.llm.factory import get_llm_provider
from app.llm.mock import MockProvider
from app.main import app

JSON = {"Content-Type": "application/json"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    # La validación falla antes de usar la sesión: no hace falta base de datos.
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_embedder] = FakeEmbedder
    app.dependency_overrides[get_llm_provider] = MockProvider
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _message(response: httpx2.Response) -> str:
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    message: str = response.json()["error"]["message"]
    return message


def test_malformed_json_body_has_a_clear_message(client: TestClient) -> None:
    response = client.post("/ask", content=b'{"question": ', headers=JSON)

    assert _message(response) == "El cuerpo de la petición no es JSON válido"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"", "Falta el cuerpo de la petición"),
        (b"[1]", "El cuerpo de la petición debe ser un objeto JSON"),
        (b"{}", "Falta la pregunta"),
        (b'{"question": "a"}', "La pregunta debe tener al menos 3 caracteres"),
        (b'{"question": 5}', "La pregunta debe ser texto"),
        (
            b'{"question": "hola", "document_ids": []}',
            "La lista de documentos (document_ids) debe tener al menos 1 elemento(s)",
        ),
        (
            b'{"question": "hola", "document_ids": ["x"]}',
            "La lista de documentos (document_ids) contiene un id que no es un UUID válido",
        ),
    ],
)
def test_ask_body_errors_are_readable(client: TestClient, body: bytes, expected: str) -> None:
    assert _message(client.post("/ask", content=body, headers=JSON)) == expected


def test_question_and_list_limits_are_explained(client: TestClient) -> None:
    too_long = client.post("/ask", json={"question": "a" * 1001})
    too_many = client.post(
        "/ask",
        json={"question": "hola", "document_ids": [str(uuid.uuid4()) for _ in range(51)]},
    )

    assert _message(too_long) == "La pregunta debe tener como máximo 1000 caracteres"
    assert _message(too_many) == (
        "La lista de documentos (document_ids) debe tener como máximo 50 elementos"
    )


def test_header_path_and_file_errors_are_readable(client: TestClient) -> None:
    bad_org = client.get("/documents", headers={"X-Org-Id": "con espacio"})
    bad_id = client.get("/documents/123")
    no_file = client.post("/documents", files={"otro": ("a.pdf", b"%PDF-")})

    assert _message(bad_org).startswith("El header X-Org-Id solo admite letras")
    assert _message(bad_id) == "El id del documento no es un UUID válido"
    assert _message(no_file) == "Falta el archivo (campo file)"


def test_messages_never_expose_internal_locations(client: TestClient) -> None:
    response = client.post("/ask", json={"question": 5, "document_ids": ["x"]})

    message = _message(response)
    assert "body." not in message
    assert "La pregunta debe ser texto" in message
    assert "UUID" in message
