"""Prova de isolamento com recurso e rotas que existem somente nos testes."""

import asyncio
import io
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Depends, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, MetaData, String, Table, Uuid, text

from fall.api.main import create_app
from fall.api.ownership import authenticated_owner
from fall.application.access import NewSession
from fall.application.ownership import OwnerScope
from fall.config import Environment, Settings
from fall.integrations.session_tokens import OpaqueSessionTokens
from fall.observability import Component, _OperationalFormatter
from fall.persistence.access import PostgresSessionRepository, PostgresUserRepository
from fall.persistence.database import create_database_engine
from fall.persistence.ownership import OwnedRepository


@pytest.fixture
def owner_data(disposable_database, monkeypatch):
    monkeypatch.setenv("FALL_ENVIRONMENT", "test")
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    engine = create_database_engine(disposable_database)
    owner, other, owned_id, other_id = (uuid4() for _ in range(4))
    instant = datetime.now(UTC)
    assert PostgresUserRepository(engine).create_active(
        owner, login="owner", password_hash="synthetic-hash", created_at=instant
    )
    tokens = OpaqueSessionTokens()
    token = tokens.issue()
    assert PostgresSessionRepository(engine).create(
        NewSession(uuid4(), owner, tokens.digest(token), instant, instant + timedelta(hours=8))
    )
    table = Table(
        "synthetic_owned_resources", MetaData(),
        Column("id", Uuid, primary_key=True),
        Column("user_id", Uuid, nullable=False),
        Column("value", String, nullable=False),
    )
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO users (id, login, password_hash, is_active, created_at, updated_at)
            VALUES (:id, 'other', 'synthetic-hash', false, :instant, :instant)
        """), {"id": other, "instant": instant})
        connection.execute(text("""
            CREATE TABLE synthetic_owned_resources (
                id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id), value TEXT NOT NULL
            )
        """))
        connection.execute(table.insert(), [
            {"id": owned_id, "user_id": owner, "value": "owned-value"},
            {"id": other_id, "user_id": other, "value": "other-private-value"},
        ])
    try:
        yield engine, table, owner, other, owned_id, other_id, token
    finally:
        engine.dispose()


def test_repository_requires_owner_and_filters_reads_and_mutations(owner_data):
    engine, table, owner, other, owned_id, other_id, _ = owner_data
    with engine.begin() as connection:
        with pytest.raises(TypeError):
            OwnedRepository(connection, table, None)
        with pytest.raises(TypeError):
            OwnerScope(str(owner))
        repository = OwnedRepository(connection, table, OwnerScope(owner))
        assert repository.get(owned_id)["value"] == "owned-value"
        assert repository.get(other_id) is None
        assert repository.get(uuid4()) is None
        assert repository.update(owned_id, {"value": "updated"})
        assert not repository.update(other_id, {"value": "stolen"})
        for forbidden in ({"user_id": other}, {"id": uuid4()}, {}):
            with pytest.raises(ValueError):
                repository.update(owned_id, forbidden)
        assert connection.execute(table.select().where(table.c.id == other_id)).mappings().one()[
            "value"
        ] == "other-private-value"
        assert connection.scalar(text("SELECT count(*) FROM users WHERE is_active")) == 1


def test_http_owner_is_derived_from_real_session_and_404_does_not_leak(owner_data):
    engine, table, owner, other, owned_id, other_id, token = owner_data
    app = create_app(Settings(Environment.TEST))
    request_ids = []

    class Change(BaseModel):
        model_config = ConfigDict(extra="forbid")
        value: str

    @app.get("/synthetic/{key}")
    async def read(key: UUID, scope: OwnerScope = Depends(authenticated_owner)):
        with engine.connect() as connection:
            row = OwnedRepository(connection, table, scope).get(key)
        if row is None:
            raise HTTPException(status_code=404)
        return {"value": row["value"]}

    @app.patch("/synthetic/{key}")
    async def change(key: UUID, body: Change, scope: OwnerScope = Depends(authenticated_owner)):
        with engine.begin() as connection:
            updated = OwnedRepository(connection, table, scope).update(key, {"value": body.value})
        if not updated:
            raise HTTPException(status_code=404)
        return {"value": body.value}

    async def exercise():
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {token}"}
            own = await client.get(f"/synthetic/{owned_id}", headers=headers)
            assert own.status_code == 200 and own.json() == {"value": "owned-value"}
            injected = await client.get(f"/synthetic/{other_id}?user_id={other}", headers=headers)
            absent = await client.get(f"/synthetic/{uuid4()}", headers=headers)
            denied = await client.patch(
                f"/synthetic/{other_id}", headers=headers, json={"value": "stolen"}
            )
            absent_patch = await client.patch(
                f"/synthetic/{uuid4()}", headers=headers, json={"value": "stolen"}
            )
            injection = await client.patch(
                f"/synthetic/{owned_id}", headers=headers,
                json={"value": "stolen", "user_id": str(other)},
            )
            assert injection.status_code == 422
            updated = await client.patch(
                f"/synthetic/{owned_id}", headers=headers, json={"value": "updated"}
            )
            assert updated.status_code == 200
            for response in (injected, absent, denied, absent_patch):
                assert response.status_code == 404
                error = response.json()["error"]
                assert {key: value for key, value in error.items() if key != "request_id"} == {
                    "code": "NOT_FOUND", "message": "O recurso não foi encontrado.",
                    "retryable": False,
                }
                assert error["request_id"] == response.headers["X-Request-ID"]
                assert "other-private-value" not in response.text
            for response in (own, injected, absent, denied, absent_patch, injection, updated):
                UUID(response.headers["X-Request-ID"])
                request_ids.append(response.headers["X-Request-ID"])
                assert token not in response.text

    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(_OperationalFormatter(Component.API))
    logger = logging.getLogger("fall.api.correlation")
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        asyncio.run(asyncio.wait_for(exercise(), timeout=15))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
    logs = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [entry["request_id"] for entry in logs] == request_ids
    assert [entry["status_code"] for entry in logs] == [200, 404, 404, 404, 404, 422, 200]
    with engine.connect() as connection:
        rows = connection.execute(table.select()).mappings().all()
    assert {row["id"]: row["value"] for row in rows} == {
        owned_id: "updated", other_id: "other-private-value"
    }
    assert token not in output.getvalue()
    assert "other-private-value" not in output.getvalue()
