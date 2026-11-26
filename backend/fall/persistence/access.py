"""Repositórios PostgreSQL de usuários e atividade de sessões."""

from datetime import datetime, timedelta
from uuid import UUID

from psycopg.errors import UniqueViolation
from sqlalchemy import Connection, Engine, RowMapping, bindparam, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from fall.application.access import NewSession, UserCredentials
from fall.application.ports import Clock
from fall.domain.time import as_utc
from fall.persistence.types import UTCInstant


_FIND_USER = text(
    "SELECT id AS user_id, password_hash, is_active FROM users WHERE login = :login"
)
_CREATE_USER = text("""
    INSERT INTO users (id, login, password_hash, is_active, created_at, updated_at)
    VALUES (:user_id, :login, :password_hash, true, :created_at, :created_at)
""").bindparams(bindparam("created_at", type_=UTCInstant()))
_USER_CONFLICTS = {"uq_users_login", "uq_users_active"}
_CREATE_SESSION = text("""
    INSERT INTO sessions (id, user_id, token_digest, created_at, last_seen_at, absolute_expires_at)
    SELECT :id, users.id, :token_digest, :created_at, :created_at, :absolute_expires_at
    FROM users
    WHERE users.id = :user_id AND users.is_active
    FOR SHARE OF users
    RETURNING id
""").bindparams(
    bindparam("created_at", type_=UTCInstant()),
    bindparam("absolute_expires_at", type_=UTCInstant()),
)
_LOCK_SESSION = text("""
    SELECT sessions.id, sessions.user_id, sessions.last_seen_at,
           sessions.absolute_expires_at, sessions.revoked_at, users.is_active
    FROM sessions JOIN users ON users.id = sessions.user_id
    WHERE sessions.token_digest = :token_digest
    FOR UPDATE OF sessions FOR SHARE OF users
""").columns(
    last_seen_at=UTCInstant(),
    absolute_expires_at=UTCInstant(),
    revoked_at=UTCInstant(),
)
_TOUCH_SESSION = text("""
    UPDATE sessions SET last_seen_at = GREATEST(last_seen_at, :instant) WHERE id = :id
""").bindparams(bindparam("instant", type_=UTCInstant()))
_REVOKE_SESSION = text("""
    UPDATE sessions SET revoked_at = :instant WHERE id = :id
""").bindparams(bindparam("instant", type_=UTCInstant()))


class AccessPersistenceError(RuntimeError):
    """Falha de acesso ao banco com mensagem pública fixa."""


def _lock_eligible_session(
    connection: Connection, token_digest: bytes, clock: Clock, idle_timeout: timedelta
) -> tuple[RowMapping, datetime] | None:
    session = connection.execute(
        _LOCK_SESSION, {"token_digest": token_digest}
    ).mappings().one_or_none()
    if session is None or not session["is_active"] or session["revoked_at"] is not None:
        return None
    instant = as_utc(clock.now())
    if (
        instant >= session["last_seen_at"] + idle_timeout
        or instant >= session["absolute_expires_at"]
    ):
        return None
    return session, instant


class PostgresUserRepository:
    def __init__(self, engine: Engine):
        self._engine = engine

    def find_by_login(self, login: str) -> UserCredentials | None:
        try:
            with self._engine.connect() as connection:
                row = connection.execute(_FIND_USER, {"login": login}).mappings().one_or_none()
        except SQLAlchemyError:
            pass
        else:
            return UserCredentials(**row) if row is not None else None
        raise AccessPersistenceError("Não foi possível consultar o usuário.")

    def create_active(
        self, user_id: UUID, *, login: str, password_hash: str, created_at: datetime
    ) -> bool:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    _CREATE_USER,
                    {
                        "user_id": user_id,
                        "login": login,
                        "password_hash": password_hash,
                        "created_at": created_at,
                    },
                )
        except IntegrityError as error:
            violation = error.orig
            if (
                isinstance(violation, UniqueViolation)
                and violation.diag.constraint_name in _USER_CONFLICTS
            ):
                return False
        except SQLAlchemyError:
            pass
        else:
            return True
        raise AccessPersistenceError("Não foi possível criar o usuário.")


class PostgresSessionRepository:
    def __init__(self, engine: Engine):
        self._engine = engine

    def create(self, session: NewSession) -> bool:
        try:
            with self._engine.begin() as connection:
                session_id = connection.scalar(
                    _CREATE_SESSION,
                    {
                        "id": session.id,
                        "user_id": session.user_id,
                        "token_digest": session.token_digest,
                        "created_at": session.created_at,
                        "absolute_expires_at": session.absolute_expires_at,
                    },
                )
        except SQLAlchemyError:
            pass
        else:
            return session_id is not None
        raise AccessPersistenceError("Não foi possível criar a sessão.")

    def authenticate_and_touch(
        self, token_digest: bytes, *, clock: Clock, idle_timeout: timedelta
    ) -> UUID | None:
        try:
            with self._engine.begin() as connection:
                eligible = _lock_eligible_session(connection, token_digest, clock, idle_timeout)
                if eligible is None:
                    return None
                session, instant = eligible
                connection.execute(_TOUCH_SESSION, {"id": session["id"], "instant": instant})
                return session["user_id"]
        except SQLAlchemyError:
            pass
        raise AccessPersistenceError("Não foi possível validar a sessão.")

    def revoke_current(
        self, token_digest: bytes, *, clock: Clock, idle_timeout: timedelta
    ) -> bool:
        try:
            with self._engine.begin() as connection:
                eligible = _lock_eligible_session(connection, token_digest, clock, idle_timeout)
                if eligible is None:
                    return False
                session, instant = eligible
                connection.execute(_REVOKE_SESSION, {"id": session["id"], "instant": instant})
                return True
        except SQLAlchemyError:
            pass
        raise AccessPersistenceError("Não foi possível revogar a sessão.")
