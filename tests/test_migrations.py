"""Ciclo de migrações em um PostgreSQL descartável."""

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
    previous_head = ScriptDirectory.from_config(config).get_current_head()
    revision = command.revision(config, message="synthetic template check")
    assert revision.down_revision == previous_head
    assert callable(revision.module.upgrade)
    assert callable(revision.module.downgrade)
    assert ScriptDirectory.from_config(config).get_current_head() == revision.revision


def test_access_revision_round_trip_preserves_unrelated_data(
    disposable_database, monkeypatch
) -> None:
    monkeypatch.setenv("FALL_ENVIRONMENT", "test")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(config, "0001_baseline")
        with engine.connect() as connection:
            assert MigrationContext.configure(connection).get_current_revision() == "0001_baseline"
            assert inspect(connection).get_table_names() == ["alembic_version"]

        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE migration_probe (note text NOT NULL)"))
            connection.execute(text("INSERT INTO migration_probe (note) VALUES ('synthetic')"))

        for target in ("0001_baseline", "base"):
            command.upgrade(config, "head")
            with engine.connect() as connection:
                assert set(inspect(connection).get_table_names()) == {
                    "alembic_version", "migration_probe", "sessions", "users"
                }
                assert connection.scalar(text("SELECT note FROM migration_probe")) == "synthetic"

            command.downgrade(config, target)
            with engine.connect() as connection:
                assert set(inspect(connection).get_table_names()) == {"alembic_version", "migration_probe"}
                assert MigrationContext.configure(connection).get_current_revision() == (
                    "0001_baseline" if target == "0001_baseline" else None
                )
                assert connection.scalar(text("SELECT note FROM migration_probe")) == "synthetic"
    finally:
        engine.dispose()
