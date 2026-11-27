"""Exercita o login HTTP com PostgreSQL e os formatos públicos de acesso."""

import hashlib
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from time import monotonic
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from fall.api.access import CurrentUser, SessionGrant
from fall.api.main import create_app
from fall.application.access import SessionTokens
from fall.application.ports import Clock
from fall.application.sessions import authenticate_session, revoke_session
from fall.config import Environment, Settings
from fall.integrations.clock import SystemClock
from fall.integrations.passwords import Argon2PasswordHasher
from fall.integrations.session_tokens import OpaqueSessionTokens
from fall.persistence.access import (
    AccessPersistenceError,
    PostgresSessionRepository,
    PostgresUserRepository,
)
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


class _MutableClock:
    def __init__(self, instant: datetime):
        self.instant = instant

    def now(self) -> datetime:
        return self.instant


@pytest.fixture
async def issued_session(session_database, client):
    engine, user_id, _ = session_database
    response = await client.post("/v1/sessions", json={"login": _LOGIN, "password": _PASSWORD})
    assert response.status_code == 200
    return engine, user_id, response.json()["access_token"]


def _authenticate(token, engine, clock):
    return authenticate_session(
        token,
        sessions=PostgresSessionRepository(engine),
        tokens=OpaqueSessionTokens(),
        clock=clock,
    )


async def test_valid_session_records_authenticated_activity(issued_session):
    engine, user_id, token = issued_session
    instant = _FixedClock().now() + timedelta(minutes=1)

    assert _authenticate(token, engine, _MutableClock(instant)) == user_id

    with engine.connect() as connection:
        activity = connection.scalar(text("SELECT last_seen_at FROM sessions"))
    assert activity == instant


@pytest.mark.parametrize(
    ("elapsed", "valid"),
    [
        (timedelta(minutes=15) - timedelta(microseconds=1), True),
        (timedelta(minutes=15), False),
        (timedelta(minutes=15, microseconds=1), False),
    ],
)
async def test_session_idle_limit_is_exclusive(issued_session, elapsed, valid):
    engine, user_id, token = issued_session
    instant = _FixedClock().now() + elapsed

    owner = _authenticate(token, engine, _MutableClock(instant))

    assert owner == (user_id if valid else None)
    with engine.connect() as connection:
        activity = connection.scalar(text("SELECT last_seen_at FROM sessions"))
    assert activity == (instant if valid else _FixedClock().now())


@pytest.mark.parametrize(
    ("elapsed", "valid"),
    [
        (timedelta(hours=8) - timedelta(microseconds=1), True),
        (timedelta(hours=8), False),
        (timedelta(hours=8, microseconds=1), False),
    ],
)
async def test_session_absolute_limit_is_exclusive(issued_session, elapsed, valid):
    engine, user_id, token = issued_session
    recent_activity = _FixedClock().now() + timedelta(hours=7, minutes=59)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE sessions SET last_seen_at = :instant"), {"instant": recent_activity}
        )
    instant = _FixedClock().now() + elapsed

    owner = _authenticate(token, engine, _MutableClock(instant))

    assert owner == (user_id if valid else None)
    with engine.connect() as connection:
        session = connection.execute(text("SELECT * FROM sessions")).mappings().one()
    assert session["last_seen_at"] == (instant if valid else recent_activity)
    assert session["absolute_expires_at"] == _FixedClock().now() + timedelta(hours=8)


@pytest.mark.parametrize("state", ["inactive", "revoked"])
async def test_unavailable_session_cannot_record_activity(issued_session, state):
    engine, _, token = issued_session
    with engine.begin() as connection:
        if state == "inactive":
            connection.execute(text("UPDATE users SET is_active = false"))
        else:
            connection.execute(
                text("UPDATE sessions SET revoked_at = :instant"),
                {"instant": _FixedClock().now()},
            )

    assert _authenticate(
        token, engine, _MutableClock(_FixedClock().now() + timedelta(minutes=1))
    ) is None

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT last_seen_at FROM sessions")) == _FixedClock().now()


@pytest.mark.parametrize(
    "token",
    [
        None, "", "short", "a" * 42, "a" * 44,
        "a" * 42 + "=", "a" * 42 + "é", "a" * 42 + "B",
        "a" * 42 + "/", "a" * 42 + "\n", " " + "a" * 42,
    ],
)
def test_malformed_session_token_is_rejected_without_database(disposable_database, token):
    engine = create_database_engine(disposable_database)
    try:
        assert _authenticate(token, engine, _MutableClock(_FixedClock().now())) is None
    finally:
        engine.dispose()


async def test_authenticated_activity_never_moves_backwards(issued_session):
    engine, user_id, token = issued_session
    latest = _FixedClock().now() + timedelta(minutes=2)
    clock = _MutableClock(latest)
    assert _authenticate(token, engine, clock) == user_id
    clock.instant -= timedelta(minutes=1)

    assert _authenticate(token, engine, clock) == user_id

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT last_seen_at FROM sessions")) == latest


@pytest.mark.parametrize("unavailable_table", ["users", "sessions"])
async def test_session_validation_preserves_safe_infrastructure_errors(
    issued_session, unavailable_table
):
    engine, _, token = issued_session
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {unavailable_table} RENAME TO unavailable"))

    with pytest.raises(AccessPersistenceError) as failure:
        _authenticate(token, engine, _MutableClock(_FixedClock().now()))

    error = failure.value
    assert str(error) == "Não foi possível validar a sessão."
    assert error.__context__ is None
    assert error.__cause__ is None
    assert token not in str(error)
    assert "SELECT" not in str(error)


@pytest.mark.parametrize("altered", [False, True])
async def test_unknown_session_token_cannot_record_activity(issued_session, altered):
    engine, _, token = issued_session
    if altered:
        rejected = ("A" if token[0] != "A" else "B") + token[1:]
    else:
        rejected = OpaqueSessionTokens().issue()

    assert _authenticate(
        rejected, engine, _MutableClock(_FixedClock().now() + timedelta(minutes=1))
    ) is None

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT last_seen_at FROM sessions")) == _FixedClock().now()


async def test_repeated_activity_cannot_extend_the_absolute_expiration(issued_session):
    engine, user_id, token = issued_session
    clock = _MutableClock(_FixedClock().now())
    for minute in range(14, 480, 14):
        clock.instant = _FixedClock().now() + timedelta(minutes=minute)
        assert _authenticate(token, engine, clock) == user_id
    clock.instant = _FixedClock().now() + timedelta(hours=8) - timedelta(microseconds=1)
    assert _authenticate(token, engine, clock) == user_id
    clock.instant += timedelta(microseconds=1)

    assert _authenticate(token, engine, clock) is None

    with engine.connect() as connection:
        session = connection.execute(text("SELECT * FROM sessions")).mappings().one()
    assert session["absolute_expires_at"] == _FixedClock().now() + timedelta(hours=8)
    assert session["last_seen_at"] == clock.instant - timedelta(microseconds=1)


@pytest.mark.parametrize("path", ["/health", "/openapi.json", "/v1/sessions"])
async def test_public_request_cannot_record_session_activity(
    issued_session, client, monkeypatch, path
):
    engine, _, token = issued_session
    instant = _FixedClock().now() + timedelta(minutes=1)
    monkeypatch.setattr(SystemClock, "now", lambda self: instant)
    headers = {"Authorization": f"Bearer {token}"}
    if path == "/v1/sessions":
        response = await client.post(
            path, headers=headers, json={"login": _LOGIN, "password": "wrong-sentinel"}
        )
        assert response.status_code == 401
    else:
        response = await client.get(path, headers=headers)
        assert response.status_code == 200

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT last_seen_at FROM sessions")) == _FixedClock().now()


async def test_expired_session_requires_another_password_login(issued_session, client, monkeypatch):
    engine, user_id, old_token = issued_session
    clock = _MutableClock(_FixedClock().now() + timedelta(minutes=15))
    assert _authenticate(old_token, engine, clock) is None
    monkeypatch.setattr(SystemClock, "now", lambda self: clock.now())
    rejected = await client.post(
        "/v1/sessions", json={"login": _LOGIN, "password": "wrong-sentinel"}
    )
    assert rejected.status_code == 401

    response = await client.post("/v1/sessions", json={"login": _LOGIN, "password": _PASSWORD})

    assert response.status_code == 200
    new_token = response.json()["access_token"]
    assert new_token != old_token
    assert _authenticate(new_token, engine, clock) == user_id
    assert _authenticate(old_token, engine, clock) is None
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM sessions")) == 2


async def test_session_clock_is_read_after_both_rows_are_locked(issued_session):
    engine, user_id, token = issued_session
    checked = []

    class LockCheckingClock:
        def now(self):
            for table in ("sessions", "users"):
                with engine.connect() as connection:
                    with pytest.raises(OperationalError) as locked:
                        connection.execute(text(f"SELECT id FROM {table} FOR UPDATE NOWAIT"))
                    assert locked.value.orig.sqlstate == "55P03"
                checked.append(table)
            return _FixedClock().now() + timedelta(minutes=1)

    assert _authenticate(token, engine, LockCheckingClock()) == user_id
    assert checked == ["sessions", "users"]


async def test_session_idle_expiration_uses_elapsed_time_across_dst(
    session_database, disposable_database, client, monkeypatch
):
    login_at = datetime(2026, 10, 25, 0, 50, tzinfo=timezone.utc)
    monkeypatch.setattr(SystemClock, "now", lambda self: login_at)
    response = await client.post("/v1/sessions", json={"login": _LOGIN, "password": _PASSWORD})
    assert response.status_code == 200
    token = response.json()["access_token"]
    engine = create_database_engine(
        disposable_database.update_query_dict({"options": "-c timezone=Europe/London"})
    )
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SHOW TimeZone")) == "Europe/London"
            previous_activity = connection.scalar(text("SELECT last_seen_at FROM sessions"))
        assert previous_activity.utcoffset() == timedelta(hours=1)
        now = login_at + timedelta(minutes=20)

        assert _authenticate(token, engine, _MutableClock(now)) is None

        with engine.connect() as connection:
            activity = connection.scalar(text("SELECT last_seen_at FROM sessions"))
        assert activity.astimezone(timezone.utc) == login_at
    finally:
        engine.dispose()


def _revoke(token, engine, clock):
    return revoke_session(
        token, sessions=PostgresSessionRepository(engine),
        tokens=OpaqueSessionTokens(), clock=clock,
    )


async def test_revocation_is_observed_by_a_new_application_instance(
    issued_session, disposable_database
):
    engine, _, token = issued_session
    instant = _FixedClock().now() + timedelta(minutes=1)
    assert _revoke(token, engine, _MutableClock(instant)) is True
    new_engine = create_database_engine(disposable_database)
    try:
        assert _authenticate(token, new_engine, _MutableClock(instant)) is None
        with new_engine.connect() as connection:
            row = connection.execute(text("SELECT * FROM sessions")).mappings().one()
        assert row["revoked_at"] == instant
        assert row["last_seen_at"] == _FixedClock().now()
        assert row["absolute_expires_at"] == _FixedClock().now() + timedelta(hours=8)
    finally:
        new_engine.dispose()


@pytest.mark.parametrize("state", ["unknown", "inactive", "revoked", "idle", "absolute"])
async def test_revocation_refuses_an_ineligible_session(issued_session, state):
    engine, _, token = issued_session
    instant = _FixedClock().now() + timedelta(minutes=1)
    with engine.begin() as connection:
        if state == "inactive":
            connection.execute(text("UPDATE users SET is_active = false"))
        elif state == "revoked":
            connection.execute(text("UPDATE sessions SET revoked_at = :instant"),
                               {"instant": _FixedClock().now()})
    if state == "unknown":
        token = OpaqueSessionTokens().issue()
    elif state == "idle":
        instant = _FixedClock().now() + timedelta(minutes=15)
    elif state == "absolute":
        instant = _FixedClock().now() + timedelta(hours=8)
        with engine.begin() as connection:
            connection.execute(text("UPDATE sessions SET last_seen_at = :instant"),
                               {"instant": instant - timedelta(minutes=1)})
    with engine.connect() as connection:
        before = dict(connection.execute(text("SELECT * FROM sessions")).mappings().one())

    assert _revoke(token, engine, _MutableClock(instant)) is False

    with engine.connect() as connection:
        assert dict(connection.execute(text("SELECT * FROM sessions")).mappings().one()) == before


@pytest.mark.parametrize("token", [None, "", "malformed", "a" * 42 + "é"])
def test_revocation_refuses_malformed_token_without_query(disposable_database, token):
    engine = create_database_engine(disposable_database)
    try:
        assert _revoke(token, engine, _MutableClock(_FixedClock().now())) is False
    finally:
        engine.dispose()


@pytest.mark.parametrize("table", ["sessions", "users"])
async def test_revocation_preserves_safe_infrastructure_errors(issued_session, table):
    engine, _, token = issued_session
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table} RENAME TO unavailable"))
    with pytest.raises(AccessPersistenceError) as failure:
        _revoke(token, engine, _MutableClock(_FixedClock().now()))
    assert str(failure.value) == "Não foi possível revogar a sessão."
    assert failure.value.__context__ is None
    assert failure.value.__cause__ is None


async def test_revocation_preserves_another_session(issued_session, client):
    engine, user_id, token = issued_session
    response = await client.post("/v1/sessions", json={"login": _LOGIN, "password": _PASSWORD})
    other_token = response.json()["access_token"]
    instant = _FixedClock().now() + timedelta(minutes=1)
    assert _revoke(token, engine, _MutableClock(instant)) is True
    assert _authenticate(other_token, engine, _MutableClock(instant)) == user_id
    assert _authenticate(token, engine, _MutableClock(instant)) is None


class _BlockingClock(_MutableClock):
    def __init__(self, instant):
        super().__init__(instant)
        self.locked = Event()
        self.release = Event()

    def now(self):
        self.locked.set()
        assert self.release.wait(10), "A operação não liberou o relógio controlado."
        return self.instant


def _wait_for_session_lock(engine):
    deadline = monotonic() + 10
    polling_interval = Event()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as monitor:
        while monotonic() < deadline:
            waiting = monitor.scalar(text("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_stat_activity
                    WHERE datname = current_database() AND pid <> pg_backend_pid()
                      AND wait_event_type = 'Lock'
                      AND query LIKE '%FROM sessions JOIN users%'
                )
            """))
            if waiting:
                return
            polling_interval.wait(0.01)
    pytest.fail("A segunda operação não aguardou o bloqueio da sessão.")


@pytest.mark.parametrize("first_operation", ["revoke", "touch"])
async def test_concurrent_activity_cannot_undo_revocation(issued_session, first_operation):
    engine, user_id, token = issued_session
    first_clock = _BlockingClock(_FixedClock().now() + timedelta(minutes=1))
    second_clock = _MutableClock(_FixedClock().now() + timedelta(minutes=2))
    first_call = _revoke if first_operation == "revoke" else _authenticate
    second_call = _authenticate if first_operation == "revoke" else _revoke
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_call, token, engine, first_clock)
        try:
            assert first_clock.locked.wait(10)
            second = pool.submit(second_call, token, engine, second_clock)
            _wait_for_session_lock(engine)
        finally:
            first_clock.release.set()
        assert first.result(timeout=10) == (True if first_operation == "revoke" else user_id)
        assert second.result(timeout=10) == (None if first_operation == "revoke" else True)
    assert _authenticate(token, engine, second_clock) is None
    with engine.connect() as connection:
        session = connection.execute(text("SELECT * FROM sessions")).mappings().one()
    assert session["revoked_at"] == (
        first_clock.instant if first_operation == "revoke" else second_clock.instant
    )
    assert session["last_seen_at"] == (
        _FixedClock().now() if first_operation == "revoke" else first_clock.instant
    )
    assert session["absolute_expires_at"] == _FixedClock().now() + timedelta(hours=8)


async def test_concurrent_activity_preserves_the_latest_instant(issued_session):
    engine, user_id, token = issued_session
    first_clock = _BlockingClock(_FixedClock().now() + timedelta(minutes=2))
    second_clock = _MutableClock(_FixedClock().now() + timedelta(minutes=1))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_authenticate, token, engine, first_clock)
        try:
            assert first_clock.locked.wait(10)
            second = pool.submit(_authenticate, token, engine, second_clock)
            _wait_for_session_lock(engine)
        finally:
            first_clock.release.set()
        assert first.result(timeout=10) == user_id
        assert second.result(timeout=10) == user_id
    with engine.connect() as connection:
        session = connection.execute(text("SELECT * FROM sessions")).mappings().one()
    assert session["last_seen_at"] == first_clock.instant
    assert session["absolute_expires_at"] == _FixedClock().now() + timedelta(hours=8)


@pytest.mark.parametrize("operation", ["touch", "revoke"])
@pytest.mark.parametrize("limit", ["idle", "absolute"])
async def test_session_expiring_while_waiting_cannot_be_reactivated(
    issued_session, operation, limit
):
    engine, _, token = issued_session
    boundary = _FixedClock().now() + (
        timedelta(minutes=15) if limit == "idle" else timedelta(hours=8)
    )
    if limit == "absolute":
        with engine.begin() as connection:
            connection.execute(text("UPDATE sessions SET last_seen_at = :instant"),
                               {"instant": boundary - timedelta(minutes=1)})
    with engine.connect() as connection:
        before = dict(connection.execute(text("SELECT * FROM sessions")).mappings().one())
    clock = _MutableClock(boundary - timedelta(microseconds=1))
    call = _authenticate if operation == "touch" else _revoke
    with engine.begin() as blocker:
        blocker.execute(text("SELECT id FROM sessions FOR UPDATE"))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(call, token, engine, clock)
            try:
                _wait_for_session_lock(engine)
                clock.instant = boundary
            finally:
                blocker.commit()
            assert future.result(timeout=10) is (None if operation == "touch" else False)
    with engine.connect() as connection:
        assert dict(connection.execute(text("SELECT * FROM sessions")).mappings().one()) == before
