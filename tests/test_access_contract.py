"""Exercita o login HTTP com PostgreSQL e os formatos públicos de acesso."""

import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from fall.api.access import CurrentUser, SessionGrant
from fall.api.main import create_app
from fall.application.access import SessionTokens
from fall.application.ports import Clock
from fall.config import Environment, Settings
from fall.integrations.clock import SystemClock
from fall.integrations.passwords import Argon2PasswordHasher
from fall.persistence.access import PostgresUserRepository
from fall.persistence.database import create_database_engine


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
        {"login": "x" * 129, "password": "input-sentinel"},
        {"login": "synthetic\x00", "password": "input-sentinel"},
        {"password": "input-sentinel"},
        {"login": "synthetic"},
    ],
)
async def test_session_request_rejects_invalid_credentials_shape(
    app: FastAPI, client: AsyncClient, body: dict[str, object]
) -> None:
    response = await client.post("/v1/sessions", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
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

    @app.post("/contract/sessions", response_model=SessionGrant)
    async def issue_grant() -> dict[str, object]:
        token = tokens.issue()
        return {
            "access_token": token,
            "absolute_expires_at": clock.now() + timedelta(hours=8),
            "token_digest": tokens.digest(token),
            "password_hash": "hash-sentinel",
        }

    response = await client.post("/contract/sessions")

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


_LOGIN = "Usuário sintético "
_PASSWORD = " senha-sintética-sentinel "


@pytest.fixture
def session_database(disposable_database, monkeypatch):
    monkeypatch.setenv("FALL_ENVIRONMENT", "test")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_database_engine(disposable_database)
    password_hash = Argon2PasswordHasher().hash(_PASSWORD)
    user_id = uuid4()
    assert PostgresUserRepository(engine).create_active(
        user_id, login=_LOGIN, password_hash=password_hash, created_at=_FixedClock().now()
    )
    monkeypatch.setattr(SystemClock, "now", lambda self: _FixedClock().now())
    try:
        yield engine, user_id, password_hash
    finally:
        engine.dispose()


async def test_login_persists_only_the_session_digest(session_database, client):
    engine, user_id, password_hash = session_database

    response = await client.post("/v1/sessions", json={"login": _LOGIN, "password": _PASSWORD})

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert UUID(response.headers["X-Request-ID"]).version == 4
    grant = response.json()
    assert set(grant) == {"access_token", "token_type", "absolute_expires_at"}
    token = grant["access_token"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
    assert grant["token_type"] == "Bearer"
    assert grant["absolute_expires_at"] == "2026-01-15T20:00:00Z"
    with engine.connect() as connection:
        session = connection.execute(text("SELECT * FROM sessions")).mappings().one()
    assert session["user_id"] == user_id
    assert bytes(session["token_digest"]) == hashlib.sha256(token.encode("ascii")).digest()
    assert session["created_at"] == session["last_seen_at"] == _FixedClock().now()
    assert session["absolute_expires_at"] == _FixedClock().now() + timedelta(hours=8)
    assert session["revoked_at"] is None
    assert token not in repr(session)
    assert password_hash not in response.text


@pytest.mark.parametrize(
    "failure",
    ["wrong_password", "unknown_login", "inactive", "login_case", "login_space", "password_space"],
)
async def test_invalid_login_has_the_same_public_error(session_database, client, failure):
    engine, _, password_hash = session_database
    login, password = _LOGIN, _PASSWORD
    if failure == "wrong_password":
        password = "wrong-password-sentinel"
    elif failure == "unknown_login":
        login = "unknown-login-sentinel"
    elif failure == "inactive":
        with engine.begin() as connection:
            connection.execute(text("UPDATE users SET is_active = false"))
    elif failure == "login_case":
        login = _LOGIN.lower()
    elif failure == "login_space":
        login = _LOGIN.rstrip()
    elif failure == "password_space":
        password = _PASSWORD.strip()

    response = await client.post("/v1/sessions", json={"login": login, "password": password})

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "AUTHENTICATION_REQUIRED",
            "message": "Uma sessão válida é necessária.",
            "request_id": response.headers["X-Request-ID"],
            "retryable": False,
        }
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM sessions")) == 0
    assert password not in response.text
    assert password_hash not in response.text


@pytest.mark.parametrize("broken_table", ["users", "sessions"])
async def test_login_database_failure_stays_an_infrastructure_error(
    session_database, app, broken_table
):
    engine, _, password_hash = session_database
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {broken_table} RENAME TO unavailable"))
    transport = ASGITransport(app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.post("/v1/sessions", json={"login": _LOGIN, "password": _PASSWORD})
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Ocorreu um erro interno.",
            "request_id": response.headers["X-Request-ID"],
            "retryable": False,
        }
    }
    assert _PASSWORD not in response.text
    assert password_hash not in response.text


async def test_invalid_password_hash_is_an_infrastructure_error(session_database, app):
    engine, _, _ = session_database
    with engine.begin() as connection:
        connection.execute(text("UPDATE users SET password_hash = 'invalid-hash-sentinel'"))
    transport = ASGITransport(app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.post("/v1/sessions", json={"login": _LOGIN, "password": _PASSWORD})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "invalid-hash-sentinel" not in response.text


async def test_malformed_login_json_uses_the_common_envelope(client):
    response = await client.post(
        "/v1/sessions", content='{"password": "input-sentinel",',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "input-sentinel" not in response.text


_LOGIN_LOG_PROBE = '''
import asyncio
import hashlib
import json
import logging

import httpx
import uvicorn
from sqlalchemy import text

from fall.api.main import create_app
from fall.config import Environment
from fall.persistence.database import create_database_engine, load_database_url

async def exercise():
    server = uvicorn.Server(uvicorn.Config(create_app, factory=True, host="127.0.0.1", port=0))
    task = asyncio.create_task(server.serve())
    tokens = []
    responses = []
    engine = create_database_engine(load_database_url(Environment.TEST))
    try:
        while not server.started:
            if task.done():
                await task
                raise RuntimeError("test server failed to start")
            await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        with engine.connect() as connection:
            user = connection.execute(text("SELECT login, password_hash FROM users")).mappings().one()
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            body = {"login": user["login"], "password": " senha-sintética-sentinel "}
            success = await client.post("/v1/sessions", json=body)
            assert success.status_code == 200
            tokens.append(success.json()["access_token"])
            responses.append(success)
            responses.append(await client.post("/v1/sessions", json=body | {"password": "wrong-sentinel"}))
            responses.append(await client.post("/v1/sessions", json=body | {"extra": "input-sentinel"}))
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE sessions RENAME TO unavailable"))
            responses.append(await client.post("/v1/sessions", json=body))
        assert [response.status_code for response in responses] == [200, 401, 422, 500]
        logging.getLogger("probe").exception(
            "sensitive %s", (tokens, user["password_hash"], hashlib.sha256(tokens[0].encode()).hexdigest())
        )
        print(json.dumps([response.headers["X-Request-ID"] for response in responses]))
    finally:
        server.should_exit = True
        await task
        engine.dispose()

asyncio.run(exercise())
'''


def test_login_server_logs_omit_credentials_and_internal_material(session_database):
    _, _, password_hash = session_database
    result = subprocess.run(
        [sys.executable, "-c", _LOGIN_LOG_PROBE],
        env=os.environ | {"PYTHONIOENCODING": "utf-8"},
        capture_output=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert _PASSWORD not in result.stderr
    assert password_hash not in result.stderr
    assert "sentinel" not in result.stderr
    assert "Traceback" not in result.stderr
    request_ids = json.loads(result.stdout)
    records = [json.loads(line) for line in result.stderr.splitlines()]
    finished = [record for record in records if record["event"] == "request_finished"]
    assert [record["status_code"] for record in finished] == [200, 401, 422, 500]
    assert [record["request_id"] for record in finished] == request_ids
    for record in records:
        assert set(record) <= {"timestamp", "level", "component", "event", "environment", "status_code", "request_id"}
