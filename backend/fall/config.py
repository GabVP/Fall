"""Seleção explícita do ambiente de execução."""

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class ConfigurationError(ValueError):
    """Falha de configuração com mensagem segura para exibir ao operador."""


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


@dataclass(frozen=True)
class DocumentationPolicy:
    schema: bool
    swagger: bool
    redoc: bool


_DOCUMENTATION_BY_ENVIRONMENT = {
    Environment.DEVELOPMENT: DocumentationPolicy(schema=True, swagger=True, redoc=True),
    Environment.TEST: DocumentationPolicy(schema=True, swagger=True, redoc=False),
    Environment.STAGING: DocumentationPolicy(schema=True, swagger=False, redoc=False),
    Environment.PRODUCTION: DocumentationPolicy(schema=False, swagger=False, redoc=False),
}


@dataclass(frozen=True)
class Settings:
    environment: Environment

    @property
    def documentation(self) -> DocumentationPolicy:
        return _DOCUMENTATION_BY_ENVIRONMENT[self.environment]


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Lê apenas o nome do perfil; nunca inclui o valor inválido no erro."""
    values = os.environ if environ is None else environ
    name = values.get("FALL_ENVIRONMENT", "")
    try:
        return Settings(environment=Environment(name))
    except ValueError:
        pass
    choices = ", ".join(profile.value for profile in Environment)
    raise ConfigurationError(f"FALL_ENVIRONMENT deve ser um destes valores: {choices}")
