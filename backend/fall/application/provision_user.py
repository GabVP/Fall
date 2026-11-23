"""Cria o usuário ativo do Fall pelas portas de acesso."""

from uuid import uuid4

from fall.application.access import PasswordHasher, UserRepository
from fall.application.ports import Clock


def provision_user(
    login: str,
    password: str,
    *,
    users: UserRepository,
    hasher: PasswordHasher,
    clock: Clock,
) -> bool:
    return users.create_active(
        uuid4(),
        login=login,
        password_hash=hasher.hash(password),
        created_at=clock.now(),
    )
