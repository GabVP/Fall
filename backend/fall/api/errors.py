"""Respostas públicas de erro da API."""

from collections.abc import Mapping

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse


_HTTP_ERRORS = {
    400: ("INVALID_REQUEST", "A requisição é inválida."),
    401: ("AUTHENTICATION_REQUIRED", "Uma sessão válida é necessária."),
    403: ("FORBIDDEN", "A operação não é permitida."),
    404: ("NOT_FOUND", "O recurso não foi encontrado."),
    405: ("METHOD_NOT_ALLOWED", "O método não é permitido para este recurso."),
    409: ("CONFLICT", "A operação conflita com o estado atual do recurso."),
    422: ("VALIDATION_ERROR", "Os dados da requisição são inválidos."),
    429: ("RATE_LIMITED", "O limite de requisições foi atingido."),
    503: ("SERVICE_UNAVAILABLE", "O serviço está temporariamente indisponível."),
}
_INTERNAL_ERROR = ("INTERNAL_ERROR", "Ocorreu um erro interno.")
_HTTP_ERROR = ("HTTP_ERROR", "Não foi possível atender à requisição.")
_PROTOCOL_HEADER = {
    401: "www-authenticate",
    405: "allow",
    429: "retry-after",
    503: "retry-after",
}


async def http_exception_response(request: Request, error: HTTPException) -> JSONResponse:
    allowed_header = _PROTOCOL_HEADER.get(error.status_code)
    headers = {
        name: value
        for name, value in (error.headers or {}).items()
        if name.lower() == allowed_header
    }
    return _error_response(request, error.status_code, headers)


async def request_validation_response(
    request: Request, _error: RequestValidationError
) -> JSONResponse:
    return _error_response(request, 422)


async def internal_error_response(request: Request, _error: Exception) -> JSONResponse:
    return _error_response(request, 500)


def _error_response(
    request: Request, status: int, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    default = _INTERNAL_ERROR if status >= 500 else _HTTP_ERROR
    code, message = _HTTP_ERRORS.get(status, default)
    return JSONResponse(
        status_code=status,
        headers=headers,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": request.state.request_id,
                "retryable": status in (429, 503),
            },
        },
    )
