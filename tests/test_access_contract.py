"""Exercita os formatos HTTP de acesso numa API exclusiva da suíte."""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from fall.api.access import CurrentUser, SessionCredentials, SessionGrant
from fall.api.main import create_app
from fall.application.access import SessionTokens
from fall.application.ports import Clock
from fall.config import Environment, Settings


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def app() -> FastAPI:
    return create_app(Settings(Environment.TEST))


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as http:
        yield http


@pytest.mark.parametrize(
    "body",
    [
        {"login": "synthetic", "password": "input-sentinel", "user_id": "1"},
        {"login": "", "password": "input-sentinel"},
        {"login": 1, "password": "input-sentinel"},
        {"login": "synthetic", "password": ""},
        {"login": "synthetic", "password": 1},
    ],
)
async def test_session_request_rejects_invalid_credentials_shape(
    app: FastAPI, client: AsyncClient, body: dict[str, object]
) -> None:
    @app.post("/v1/sessions")
    async def receive_credentials(_body: SessionCredentials) -> None:
        pass

    response = await client.post("/v1/sessions", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "input-sentinel" not in response.text


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 15, 12, tzinfo=timezone.utc)


class _FixtureTokens:
    def issue(self) -> str:
        return "example-session-token"

    def digest(self, token: str) -> bytes | None:
        return b"digest-sentinel" if token == self.issue() else None


async def test_session_response_only_serializes_public_grant(
    app: FastAPI, client: AsyncClient
) -> None:
    clock: Clock = _FixedClock()
    tokens: SessionTokens = _FixtureTokens()

    @app.post("/v1/sessions", response_model=SessionGrant)
    async def issue_grant() -> dict[str, object]:
        token = tokens.issue()
        return {
            "access_token": token,
            "absolute_expires_at": clock.now() + timedelta(hours=8),
            "token_digest": tokens.digest(token),
            "password_hash": "hash-sentinel",
        }

    response = await client.post("/v1/sessions")

    assert response.json() == {
        "access_token": tokens.issue(),
        "token_type": "Bearer",
        "absolute_expires_at": "2026-01-15T20:00:00Z",
    }


async def test_me_response_only_serializes_owner_id(app: FastAPI, client: AsyncClient) -> None:
    user_id = UUID("449a45d3-06f2-4d26-940c-945a9975e59b")

    @app.get("/v1/me", response_model=CurrentUser)
    async def identify_user() -> dict[str, object]:
        return {
            "user_id": user_id,
            "login": "login-sentinel",
            "password_hash": "hash-sentinel",
            "access_token": "token-sentinel",
        }

    response = await client.get("/v1/me")

    assert response.json() == {"user_id": str(user_id)}
