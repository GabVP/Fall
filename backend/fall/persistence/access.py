"""Repositórios PostgreSQL de usuários e criação de sessões."""

from datetime import datetime
from uuid import UUID

from psycopg.errors import UniqueViolation
from sqlalchemy import Engine, bindparam, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from fall.application.access import NewSession, UserCredentials
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


class AccessPersistenceError(RuntimeError):
    """Falha de acesso ao banco com mensagem pública fixa."""


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
