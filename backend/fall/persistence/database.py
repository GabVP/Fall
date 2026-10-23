"""Configuração explícita da conexão PostgreSQL para cada ambiente."""

import os
from typing import Mapping

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from fall.config import Environment


_URL_VARIABLE = {
    Environment.DEVELOPMENT: "FALL_DEVELOPMENT_DATABASE_URL",
    Environment.TEST: "FALL_TEST_DATABASE_URL",
    Environment.STAGING: "FALL_STAGING_DATABASE_URL",
    Environment.PRODUCTION: "FALL_PRODUCTION_DATABASE_URL",
}


def load_database_url(
    environment: Environment, environ: Mapping[str, str] | None = None
) -> URL:
    """Exige uma URL PostgreSQL do perfil escolhido, sem expor seu conteúdo em erros."""
    values = os.environ if environ is None else environ
    variable = _URL_VARIABLE[environment]
    raw_url = values.get(variable, "")
    if not raw_url:
        raise ValueError(f"{variable} é obrigatória")
    try:
        url = make_url(raw_url)
    except (ArgumentError, ValueError):
        raise ValueError(f"{variable} deve ser uma URL PostgreSQL válida") from None
    if url.drivername != "postgresql+psycopg" or not url.database:
        raise ValueError(f"{variable} deve usar postgresql+psycopg e informar o banco")
    return url


def create_database_engine(url: URL) -> Engine:
    """Cria o adaptador; a conexão efetiva ocorre quando uma operação a utiliza."""
    return create_engine(url, pool_pre_ping=True)
