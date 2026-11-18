"""Confere falhas seguras nos comandos de entrada do Fall."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

_SENTINEL = "fall-startup-secret-sentinel"
_API = ("uvicorn", "fall.api.main:create_app", "--factory", "--no-access-log", "--port", "0")
_WORKER = ("fall.worker.main",)
_MIGRATION = ("alembic", "upgrade", "head")


@pytest.mark.parametrize("command", [_API, _WORKER], ids=["api", "worker"])
@pytest.mark.parametrize("environment", [None, _SENTINEL])
def test_process_rejects_invalid_environment(command, environment) -> None:
    result = _run(command, environment=environment)

    assert result.returncode != 0
    assert "FALL_ENVIRONMENT deve ser um destes valores" in result.stderr
    assert "Traceback" not in result.stderr
    assert _SENTINEL not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        (None, "FALL_TEST_DATABASE_URL é obrigatória"),
        (
            f"postgresql+psycopg://user:{_SENTINEL}@localhost:invalid-port/fall_test",
            "FALL_TEST_DATABASE_URL deve ser uma URL PostgreSQL válida",
        ),
        (
            f"postgresql+psycopg://user:password@127.0.0.1/fall_test?sslmode={_SENTINEL}",
            "Não foi possível conectar ao PostgreSQL para executar migrações",
        ),
        (
            f"postgresql+psycopg://user:password@127.0.0.1/fall_test?plugin={_SENTINEL}",
            "Não foi possível conectar ao PostgreSQL para executar migrações",
        ),
    ],
)
def test_migration_hides_invalid_connection_configuration(database_url, expected) -> None:
    result = _run(_MIGRATION, environment="test", database_url=database_url)

    assert result.returncode != 0
    assert expected in result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert _SENTINEL not in result.stdout + result.stderr


def _run(command, *, environment, database_url=None):
    env = os.environ | {"PYTHONIOENCODING": "utf-8"}
    env.pop("FALL_ENVIRONMENT", None)
    env.pop("FALL_TEST_DATABASE_URL", None)
    if environment is not None:
        env["FALL_ENVIRONMENT"] = environment
    if database_url is not None:
        env["FALL_TEST_DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", *command],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
