"""Comando de provisionamento do usuário ativo."""

import argparse
import getpass
import sys
import warnings
from collections.abc import Sequence

from sqlalchemy.exc import SQLAlchemyError

from fall.application.provision_user import provision_user
from fall.config import ConfigurationError, load_settings
from fall.integrations.clock import SystemClock
from fall.integrations.passwords import Argon2PasswordHasher, PasswordHashError
from fall.persistence.access import AccessPersistenceError, PostgresUserRepository
from fall.persistence.database import create_database_engine, load_database_url


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        super().error("Informe apenas --login com o identificador do usuário.")


class _PasswordInputError(ValueError):
    pass


def _read_password() -> str:
    if sys.stdin is None or not sys.stdin.isatty():
        raise _PasswordInputError("Use um terminal interativo para digitar a senha sem eco.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Senha do Fall: ")
            confirmation = getpass.getpass("Confirme a senha: ")
    except (getpass.GetPassWarning, EOFError, OSError, KeyboardInterrupt):
        raise _PasswordInputError("Não foi possível ler a senha sem eco.") from None

    if not password:
        raise _PasswordInputError("A senha não pode estar vazia.")
    if password != confirmation:
        raise _PasswordInputError("A confirmação da senha não confere.")
    return password


def main(argv: Sequence[str] | None = None) -> int:
    parser = _ArgumentParser(
        prog="fall-provision-user",
        description="Cria o usuário ativo do Fall.",
        allow_abbrev=False,
    )
    parser.add_argument("--login", required=True, help="Identificador exato do usuário.")
    login = parser.parse_args(argv).login
    if not 1 <= len(login) <= 128 or "\x00" in login:
        print("Informe um login de 1 a 128 caracteres, sem NUL.", file=sys.stderr)
        return 2

    try:
        url = load_database_url(load_settings().environment)
        password = _read_password()
    except (ConfigurationError, _PasswordInputError) as error:
        print(str(error), file=sys.stderr)
        return 1

    try:
        engine = create_database_engine(url)
        try:
            created = provision_user(
                login,
                password,
                users=PostgresUserRepository(engine),
                hasher=Argon2PasswordHasher(),
                clock=SystemClock(),
            )
        finally:
            engine.dispose()
    except (AccessPersistenceError, PasswordHashError, SQLAlchemyError):
        print("Não foi possível provisionar o usuário.", file=sys.stderr)
        return 1
    if not created:
        print("Já existe um usuário ativo ou o login está reservado.", file=sys.stderr)
        return 1

    print("Usuário ativo provisionado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
