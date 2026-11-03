"""Errores de la API y su formato único de respuesta."""

from fastapi.responses import JSONResponse

from app.schemas.documents import ErrorDetail, ErrorOut


class ApiError(Exception):
    """Error esperado que se devuelve al cliente con su código y status HTTP."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def error_response(
    status_code: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    # trace_id se rellenará en el paso de observabilidad.
    body = ErrorOut(error=ErrorDetail(code=code, message=message, trace_id=""))
    return JSONResponse(status_code=status_code, content=body.model_dump(), headers=headers)
