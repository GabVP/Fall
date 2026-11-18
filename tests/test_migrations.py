"""Ciclo da revisão inicial em um PostgreSQL descartável."""

from pathlib import Path
from shutil import copytree

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from fall.persistence.database import create_database_engine


def test_new_revision_can_be_generated_from_the_template(tmp_path) -> None:
    root = Path(__file__).resolve().parents[1]
    scripts = tmp_path / "migrations"
    copytree(root / "backend/fall/persistence/migrations", scripts)
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(scripts))
    revision = command.revision(config, message="synthetic template check")
    assert revision.down_revision == "0001_baseline"
    assert callable(revision.module.upgrade)
    assert callable(revision.module.downgrade)
    assert ScriptDirectory.from_config(config).get_current_head() == revision.revision


def test_initial_revision_round_trip_preserves_existing_data(
    disposable_database, monkeypatch
) -> None:
    monkeypatch.setenv("FALL_ENVIRONMENT", "test")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert MigrationContext.configure(connection).get_current_revision() == "0001_baseline"
            assert inspect(connection).get_table_names() == ["alembic_version"]

        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE migration_probe (id integer PRIMARY KEY, note text NOT NULL)"))
            connection.execute(text("INSERT INTO migration_probe (id, note) VALUES (1, 'synthetic')"))

        for _ in range(2):
            command.downgrade(config, "base")
            with engine.connect() as connection:
                assert MigrationContext.configure(connection).get_current_revision() is None
                assert connection.scalar(text("SELECT note FROM migration_probe WHERE id = 1")) == "synthetic"

            command.upgrade(config, "head")
            with engine.connect() as connection:
                assert MigrationContext.configure(connection).get_current_revision() == "0001_baseline"
                assert connection.scalar(text("SELECT note FROM migration_probe WHERE id = 1")) == "synthetic"
    finally:
        engine.dispose()
