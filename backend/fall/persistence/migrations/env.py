"""Executa migrações no banco do ambiente selecionado explicitamente."""

from alembic import context

from fall.config import load_settings
from fall.persistence.database import create_database_engine, load_database_url


if context.is_offline_mode():
    raise RuntimeError("Migrações Fall exigem conexão PostgreSQL ativa")

settings = load_settings()
url = load_database_url(settings.environment)
engine = create_database_engine(url)
try:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
