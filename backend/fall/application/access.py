"""Portas de acesso consumidas pela aplicação."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from fall.application.ports import Clock


@dataclass(frozen=True)
class UserCredentials:
    user_id: UUID
    password_hash: str = field(repr=False)
    is_active: bool


@dataclass(frozen=True)
class NewSession:
    id: UUID
    user_id: UUID
    token_digest: bytes = field(repr=False)
    created_at: datetime
    absolute_expires_at: datetime


class UserRepository(Protocol):
    def find_by_login(self, login: str) -> UserCredentials | None:
        """Busca pelo login exato. Retorna None somente para login ausente."""
        ...

    def create_active(
        self, user_id: UUID, *, login: str, password_hash: str, created_at: datetime
    ) -> bool:
        """Insere sem alterar registros. Retorna False se login ou vaga já existem."""
        ...


class SessionRepository(Protocol):
    """Recebe instantes em UTC. Falhas de persistência são lançadas."""

    def create(self, session: NewSession) -> bool:
        """Insere a sessão com atividade inicial no login. False se o usuário não está ativo."""
        ...

    def authenticate_and_touch(
        self, token_digest: bytes, *, clock: Clock, idle_timeout: timedelta
    ) -> UUID | None:
        """Valida e atualiza atividade de forma atômica.

        Mede o instante após obter os bloqueios necessários. Exige usuário ativo,
        sessão sem revogação e instante estritamente anterior aos dois limites.
        Retorna o proprietário e avança a atividade somente se ela for mais antiga.
        """
        ...

    def revoke_current(
        self, token_digest: bytes, *, clock: Clock, idle_timeout: timedelta
    ) -> bool:
        """Revoga atomicamente uma sessão válida segundo as mesmas condições temporais."""
        ...


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password: str, password_hash: str) -> bool:
        """Retorna False para senha incorreta. Hash inválido é erro."""
        ...


class SessionTokens(Protocol):
    def issue(self) -> str: ...

    def digest(self, token: str) -> bytes | None:
        """Calcula o resumo persistível. Retorna None para token malformado."""
        ...
