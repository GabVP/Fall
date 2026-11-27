"""Verifica o envelope público sem usar rotas financeiras."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated

import pytest
from fastapi import Body, HTTPException
from httpx import ASGITransport, AsyncClient, Response
from starlette.types import ASGIApp

from fall.api.main import create_app
from fall.config import Environment, Settings


def test_routing_errors_use_the_common_envelope(authenticated_headers) -> None:
    app = create_app(Settings(Environment.TEST))

    async def exercise(client: AsyncClient) -> None:
        _assert_error(await client.get("/v1/absent"), 404, "NOT_FOUND", retryable=False)
        method_error = await client.post("/openapi.json")
        _assert_error(method_error, 405, "METHOD_NOT_ALLOWED", retryable=False)
        assert "GET" in method_error.headers["Allow"]

    _exercise(app, exercise, authenticated_headers)


@pytest.mark.parametrize(
    ("status", "code", "retryable", "header", "value"),
    [
        (401, "AUTHENTICATION_REQUIRED", False, "WWW-Authenticate", "Bearer"),
        (429, "RATE_LIMITED", True, "Retry-After", "10"),
        (503, "SERVICE_UNAVAILABLE", True, "Retry-After", "60"),
    ],
)
def test_expected_errors_keep_protocol_headers(status, code, retryable, header, value, authenticated_headers) -> None:
    app = create_app(Settings(Environment.TEST))

    @app.get("/v1/probe")
    async def probe() -> None:
        raise HTTPException(
            status_code=status,
            detail={"token": "error-sentinel"},
            headers={header: value, "X-Diagnostic": "header-sentinel"},
        )

    async def exercise(client: AsyncClient) -> None:
        response = await client.get("/v1/probe")
        _assert_error(response, status, code, retryable=retryable)
        assert response.headers[header] == value
        assert "X-Diagnostic" not in response.headers

    _exercise(app, exercise, authenticated_headers)


def test_validation_distinguishes_bad_input_from_bad_server_output(authenticated_headers) -> None:
    app = create_app(Settings(Environment.TEST))

    @app.post("/v1/probe", response_model=int)
    async def probe(amount: Annotated[int, Body(embed=True)]) -> str:
        return "response-sentinel"

    async def exercise(client: AsyncClient) -> None:
        _assert_error(
            await client.post("/v1/probe", json={"amount": "input-sentinel"}),
            422,
            "VALIDATION_ERROR",
            retryable=False,
        )
        _assert_error(
            await client.post("/v1/probe", json={"amount": 1}),
            500,
            "INTERNAL_ERROR",
            retryable=False,
        )

    _exercise(app, exercise, authenticated_headers)


def _exercise(app: ASGIApp, exercise: Callable[[AsyncClient], Awaitable[None]], headers) -> None:
    async def run() -> None:
        transport = ASGITransport(app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
            await exercise(client)

    asyncio.run(run())


def _assert_error(response: Response, status: int, code: str, *, retryable: bool) -> None:
    assert response.status_code == status
    assert "-sentinel" not in response.text
    assert "Traceback" not in response.text
    payload = response.json()
    assert set(payload) == {"error"}
    error = payload["error"]
    assert set(error) == {"code", "message", "request_id", "retryable"}
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert error["retryable"] is retryable
