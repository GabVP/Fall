"""Contratos dos repositórios de acesso em PostgreSQL descartável."""

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from psycopg.errors import ForeignKeyViolation
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from fall.application.access import NewSession, UserCredentials
from fall.domain.time import SAO_PAULO
from fall.persistence.access import (
    AccessPersistenceError,
    PostgresSessionRepository,
    PostgresUserRepository,
)
from fall.persistence.database import create_database_engine


_CREATED_AT = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)
_PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$synthetic-salt$synthetic-hash"
_DIGEST = b"digest-sentinel".ljust(32, b"-")


@pytest.fixture
def access_database(disposable_database, monkeypatch):
    monkeypatch.setenv("FALL_ENVIRONMENT", "test")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_database_engine(disposable_database)
    try:
        yield engine
    finally:
        engine.dispose()


def test_active_user_can_be_loaded_by_a_new_repository(
    access_database, disposable_database
) -> None:
    user_id = uuid4()
    users = PostgresUserRepository(access_database)
    assert users.create_active(
        user_id, login="Usuário ", password_hash=_PASSWORD_HASH, created_at=_CREATED_AT
    )

    new_engine = create_database_engine(disposable_database)
    try:
        users = PostgresUserRepository(new_engine)
        assert users.find_by_login("Usuário ") == UserCredentials(user_id, _PASSWORD_HASH, True)
        assert users.find_by_login("usuário ") is None
        assert users.find_by_login("Usuário") is None
    finally:
        new_engine.dispose()


def test_concurrent_creations_only_register_one_active_user(access_database) -> None:
    barrier = Barrier(2, timeout=10)
    backend_pids = set()

    def synchronize_checkout(dbapi_connection, _connection_record, _proxy) -> None:
        backend_pids.add(dbapi_connection.info.backend_pid)
        barrier.wait()

    def register(login: str) -> bool:
        users = PostgresUserRepository(access_database)
        return users.create_active(
            uuid4(), login=login, password_hash=_PASSWORD_HASH, created_at=_CREATED_AT
        )

    event.listen(access_database, "checkout", synchronize_checkout)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(register, ["synthetic-one", "synthetic-two"]))
    finally:
        event.remove(access_database, "checkout", synchronize_checkout)

    assert len(backend_pids) == 2
    assert results in ([True, False], [False, True])
    with access_database.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM users")) == 1


def test_session_persists_its_owner_and_utc_instants(
    access_database, disposable_database, session_for_active_user
) -> None:
    session = session_for_active_user
    assert PostgresSessionRepository(access_database).create(session)
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")

    new_engine = create_database_engine(disposable_database)
    try:
        with new_engine.connect() as connection:
            connection.execute(text("SET TIME ZONE 'UTC'"))
            saved = connection.execute(
                text("SELECT * FROM sessions WHERE id = :id"), {"id": session.id}
            ).one()
        assert saved.user_id == session.user_id
        assert saved.token_digest == _DIGEST
        assert saved.created_at == saved.last_seen_at == _CREATED_AT
        assert saved.absolute_expires_at == _CREATED_AT + timedelta(hours=8)
        assert saved.revoked_at is None
    finally:
        new_engine.dispose()


@pytest.fixture
def session_for_active_user(access_database) -> NewSession:
    user_id = uuid4()
    local_time = _CREATED_AT.astimezone(SAO_PAULO)
    assert PostgresUserRepository(access_database).create_active(
        user_id, login="synthetic", password_hash=_PASSWORD_HASH, created_at=local_time
    )
    return NewSession(uuid4(), user_id, _DIGEST, local_time, local_time + timedelta(hours=8))


def test_reserved_login_does_not_replace_inactive_credentials(
    access_database, session_for_active_user
) -> None:
    user_id = session_for_active_user.user_id
    with access_database.begin() as connection:
        connection.execute(text("UPDATE users SET is_active = false WHERE id = :id"), {"id": user_id})

    users = PostgresUserRepository(access_database)
    assert users.create_active(
        uuid4(), login="synthetic", password_hash="replacement-sentinel", created_at=_CREATED_AT
    ) is False
    assert users.find_by_login("synthetic") == UserCredentials(user_id, _PASSWORD_HASH, False)


@pytest.mark.parametrize("missing", [True, False], ids=["unknown-owner", "inactive-owner"])
def test_session_creation_requires_active_owner(
    access_database, session_for_active_user, missing
) -> None:
    session = session_for_active_user
    if missing:
        session = replace(session, user_id=uuid4())
    else:
        with access_database.begin() as connection:
            connection.execute(
                text("UPDATE users SET is_active = false WHERE id = :id"), {"id": session.user_id}
            )
    assert PostgresSessionRepository(access_database).create(session) is False

    with access_database.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM sessions")) == 0


def test_database_rejects_sessions_without_an_existing_owner(access_database) -> None:
    with pytest.raises(IntegrityError) as failure:
        with access_database.begin() as connection:
            connection.execute(
                text("""
                    INSERT INTO sessions
                        (id, user_id, token_digest, created_at, last_seen_at, absolute_expires_at)
                    VALUES (:id, :user_id, :digest, :login_at, :login_at, :deadline)
                """),
                dict(
                    id=uuid4(), user_id=uuid4(), digest=_DIGEST, login_at=_CREATED_AT,
                    deadline=_CREATED_AT + timedelta(hours=8),
                ),
            )
    assert isinstance(failure.value.orig, ForeignKeyViolation)


def test_session_digest_cannot_be_reused(access_database, session_for_active_user) -> None:
    sessions = PostgresSessionRepository(access_database)
    assert sessions.create(session_for_active_user)
    with pytest.raises(AccessPersistenceError):
        sessions.create(replace(session_for_active_user, id=uuid4()))

    with access_database.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM sessions")) == 1


def test_session_deadline_must_be_after_initial_activity(
    access_database, session_for_active_user
) -> None:
    session = replace(session_for_active_user, absolute_expires_at=session_for_active_user.created_at)
    with pytest.raises(AccessPersistenceError):
        PostgresSessionRepository(access_database).create(session)


def test_invalid_digest_failure_keeps_sql_parameters_private(
    access_database, session_for_active_user, caplog
) -> None:
    session = replace(session_for_active_user, token_digest=b"digest-sentinel")
    with caplog.at_level(logging.INFO, logger="sqlalchemy.engine.Engine"):
        with pytest.raises(AccessPersistenceError, match="Não foi possível criar a sessão") as failure:
            PostgresSessionRepository(access_database).create(session)

    assert failure.value.__context__ is None
    assert "digest-sentinel" not in caplog.text
