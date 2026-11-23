"""Adapta o Argon2id à proteção de senhas do Fall."""

from argon2 import PasswordHasher
from argon2.exceptions import HashingError, InvalidHashError, VerificationError, VerifyMismatchError
from argon2.profiles import RFC_9106_LOW_MEMORY


class PasswordHashError(RuntimeError):
    """Falha de hash ou verificação sem credenciais no diagnóstico."""


class Argon2PasswordHasher:
    def __init__(self) -> None:
        self._hasher = PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)

    def hash(self, password: str) -> str:
        try:
            return self._hasher.hash(password)
        except (HashingError, UnicodeError):
            pass
        raise PasswordHashError("Não foi possível proteger a senha.")

    def verify(self, password: str, password_hash: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except VerifyMismatchError:
            return False
        except (InvalidHashError, VerificationError, UnicodeError):
            pass
        raise PasswordHashError("Não foi possível verificar a senha.")
