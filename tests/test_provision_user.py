"""Provisionamento administrativo com o comando e PostgreSQL reais."""

import getpass
import os
import subprocess
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from fall.integrations.passwords import Argon2PasswordHasher, PasswordHashError
from fall.persistence.access import PostgresUserRepository
from fall.persistence.database import create_database_engine
from fall.provision_user import main


_PASSWORD = "senha-sintetica-sentinel"


@pytest.fixture
def provision_database(disposable_database, monkeypatch):
    monkeypatch.setenv("FALL_ENVIRONMENT", "test")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    return disposable_database


def _type_passwords(monkeypatch, password: str, confirmation: str) -> None:
    answers = iter((password, confirmation))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: next(answers))


def test_provisioning_saves_only_an_argon2id_hash(provision_database, monkeypatch, capsys) -> None:
    _type_passwords(monkeypatch, _PASSWORD, _PASSWORD)
    login = "Usuário "

    assert main(["--login", login]) == 0
    engine = create_database_engine(provision_database)
    try:
        user = PostgresUserRepository(engine).find_by_login(login)
        assert user is not None and user.is_active
        assert user.password_hash.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
        assert _PASSWORD not in user.password_hash
        assert Argon2PasswordHasher().verify(_PASSWORD, user.password_hash)
    finally:
        engine.dispose()
    captured = capsys.readouterr()
    assert _PASSWORD not in captured.out + captured.err
    assert user.password_hash not in captured.out + captured.err


@pytest.mark.parametrize(
    ("second_login", "deactivate"),
    [("fixture", False), ("another-fixture", False), ("fixture", True)],
)
def test_second_provisioning_reports_conflict(
    provision_database, monkeypatch, capsys, second_login, deactivate
) -> None:
    _type_passwords(monkeypatch, _PASSWORD, _PASSWORD)
    assert main(["--login", "fixture"]) == 0

    engine = create_database_engine(provision_database)
    try:
        if deactivate:
            with engine.begin() as connection:
                connection.execute(text("UPDATE users SET is_active = false"))
        users = PostgresUserRepository(engine)
        first_user = users.find_by_login("fixture")
        alternative = "senha-alternativa-sentinel"
        _type_passwords(monkeypatch, alternative, alternative)

        assert main(["--login", second_login]) == 1
        assert users.find_by_login("fixture") == first_user
        assert users.find_by_login("another-fixture") is None
    finally:
        engine.dispose()

    captured = capsys.readouterr()
    assert "Já existe um usuário ativo ou o login está reservado." in captured.err
    assert _PASSWORD not in captured.out + captured.err
    assert alternative not in captured.out + captured.err


@pytest.mark.parametrize(
    ("password", "confirmation", "message"),
    [
        ("", "", "A senha não pode estar vazia."),
        (_PASSWORD, "confirmação-sentinel", "A confirmação da senha não confere."),
    ],
)
def test_invalid_confirmation_does_not_provision(
    provision_database, monkeypatch, capsys, password, confirmation, message
) -> None:
    _type_passwords(monkeypatch, password, confirmation)

    assert main(["--login", "fixture"]) == 1

    engine = create_database_engine(provision_database)
    try:
        assert PostgresUserRepository(engine).find_by_login("fixture") is None
    finally:
        engine.dispose()
    captured = capsys.readouterr()
    assert message in captured.err
    assert "sentinel" not in captured.out + captured.err


@pytest.mark.parametrize("login", ["", "a" * 129, "invalid\x00login"])
def test_invalid_login_is_rejected_before_password_request(monkeypatch, capsys, login) -> None:
    def unexpected_password_read(_prompt):
        pytest.fail("Entrada de senha solicitada para login inválido.")

    monkeypatch.setattr(getpass, "getpass", unexpected_password_read)
    assert main(["--login", login]) == 2
    assert "login de 1 a 128 caracteres" in capsys.readouterr().err


def test_getpass_fallback_is_interrupted_before_reading(
    provision_database, monkeypatch, capsys
) -> None:
    def try_fallback(_prompt):
        warnings.warn("terminal-sentinel", getpass.GetPassWarning)
        pytest.fail("Fallback continuou até a leitura de senha com eco.")

    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(getpass, "getpass", try_fallback)
    assert main(["--login", "fixture"]) == 1

    captured = capsys.readouterr()
    assert "Não foi possível ler a senha sem eco." in captured.err
    assert "terminal-sentinel" not in captured.out + captured.err


def test_cli_rejects_redirected_input_without_echo() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "fall.provision_user", "--login", "fixture"],
        input=f"{_PASSWORD}\n{_PASSWORD}\n",
        env=os.environ | {
            "FALL_ENVIRONMENT": "test",
            "FALL_TEST_DATABASE_URL": "postgresql+psycopg://unused@127.0.0.1:1/unused",
            "PYTHONIOENCODING": "utf-8",
        },
        encoding="utf-8",
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "Use um terminal interativo para digitar a senha sem eco." in result.stderr
    assert _PASSWORD not in result.stdout + result.stderr


def test_cli_error_does_not_echo_unknown_arguments() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "fall.provision_user", "--login", "fixture", "--argumento-sentinel"],
        encoding="utf-8",
        env=os.environ | {"PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "Informe apenas --login" in result.stderr
    assert "argumento-sentinel" not in result.stdout + result.stderr


def test_cli_database_failure_uses_safe_diagnostic(disposable_database, monkeypatch, capsys) -> None:
    monkeypatch.setenv("FALL_ENVIRONMENT", "test")
    _type_passwords(monkeypatch, _PASSWORD, _PASSWORD)

    assert main(["--login", "fixture"]) == 1

    captured = capsys.readouterr()
    assert captured.err.strip() == "Não foi possível provisionar o usuário."
    assert captured.out == ""


@pytest.mark.parametrize(
    ("password", "expected"),
    [(_PASSWORD, True), ("senha-errada-sentinel", False)],
)
def test_password_verification_reports_match_for_valid_hash(password, expected) -> None:
    hasher = Argon2PasswordHasher()
    password_hash = hasher.hash(_PASSWORD)

    assert hasher.verify(password, password_hash) is expected


def test_invalid_hash_reports_a_safe_verification_error() -> None:
    hasher = Argon2PasswordHasher()
    with pytest.raises(PasswordHashError) as failure:
        hasher.verify(_PASSWORD, "hash-invalido-sentinel")

    assert failure.value.__context__ is None
    assert "sentinel" not in str(failure.value)


def test_hashing_same_password_generates_fresh_salt() -> None:
    hasher = Argon2PasswordHasher()
    first_hash = hasher.hash(_PASSWORD)
    second_hash = hasher.hash(_PASSWORD)

    assert first_hash.split("$")[-2] != second_hash.split("$")[-2]
