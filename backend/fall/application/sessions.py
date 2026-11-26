"""Emite sessões e valida sua atividade pela interface de aplicação."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fall.application.access import (
    NewSession,
    PasswordHasher,
    SessionRepository,
    SessionTokens,
    UserRepository,
)
from fall.application.ports import Clock
from fall.domain.time import as_utc


@dataclass(frozen=True)
class IssuedSession:
    access_token: str = field(repr=False)
    absolute_expires_at: datetime


def create_session(
    login: str,
    password: str,
    *,
    users: UserRepository,
    sessions: SessionRepository,
    hasher: PasswordHasher,
    tokens: SessionTokens,
    clock: Clock,
) -> IssuedSession | None:
    user = users.find_by_login(login)
    if user is None or not user.is_active or not hasher.verify(password, user.password_hash):
        return None
    token = tokens.issue()
    digest = tokens.digest(token)
    if digest is None:
        raise RuntimeError("Não foi possível emitir a sessão.")
    created_at = as_utc(clock.now())
    expires_at = created_at + timedelta(hours=8)
    if not sessions.create(NewSession(uuid4(), user.user_id, digest, created_at, expires_at)):
        return None
    return IssuedSession(token, expires_at)


def authenticate_session(
    token: str | None,
    *,
    sessions: SessionRepository,
    tokens: SessionTokens,
    clock: Clock,
) -> UUID | None:
    """Retorna o proprietário apenas após validar e registrar a atividade."""
    if token is None:
        return None
    digest = tokens.digest(token)
    if digest is None:
        return None
    return sessions.authenticate_and_touch(
        digest, clock=clock, idle_timeout=timedelta(minutes=15)
    )
