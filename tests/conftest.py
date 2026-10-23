"""PostgreSQL isolado por teste de integração."""

import os
from uuid import uuid4

import pytest

from fall.config import Environment
from fall.persistence.database import create_database_engine, load_database_url


@pytest.fixture
def disposable_database(monkeypatch):
    if not os.environ.get("FALL_TEST_DATABASE_URL"):
        pytest.skip("Defina FALL_TEST_DATABASE_URL para o teste PostgreSQL")

    source_url = load_database_url(Environment.TEST)
    database_name = f"fall_migration_{uuid4().hex}"
    admin_engine = create_database_engine(source_url).execution_options(
        isolation_level="AUTOCOMMIT"
    )
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        temporary_url = source_url.set(database=database_name)
        monkeypatch.setenv(
            "FALL_TEST_DATABASE_URL", temporary_url.render_as_string(hide_password=False)
        )
        yield temporary_url
    finally:
        try:
            with admin_engine.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
        finally:
            admin_engine.dispose()
