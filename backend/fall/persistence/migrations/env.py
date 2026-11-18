"""Executa migrações no banco do ambiente selecionado explicitamente."""

from alembic import context
from alembic.util import CommandError
from sqlalchemy.exc import SQLAlchemyError

from fall.config import ConfigurationError, load_settings
from fall.persistence.database import create_database_engine, load_database_url


if context.is_offline_mode():
    raise RuntimeError("Migrações Fall exigem conexão PostgreSQL ativa")

try:
    settings = load_settings()
    url = load_database_url(settings.environment)
except ConfigurationError as error:
    raise CommandError(str(error)) from None

engine = None
try:
    try:
        engine = create_database_engine(url)
        connection = engine.connect()
    except SQLAlchemyError:
        raise CommandError("Não foi possível conectar ao PostgreSQL para executar migrações") from None
    with connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()
finally:
    if engine is not None:
        engine.dispose()
