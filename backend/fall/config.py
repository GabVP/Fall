"""Seleção explícita do ambiente de execução."""

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


@dataclass(frozen=True)
class Settings:
    environment: Environment

    @property
    def api_docs_enabled(self) -> bool:
        return self.environment in {Environment.DEVELOPMENT, Environment.TEST}


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Lê apenas o nome do perfil; nunca inclui o valor inválido no erro."""
    values = os.environ if environ is None else environ
    name = values.get("FALL_ENVIRONMENT", "")
    try:
        environment = Environment(name)
    except ValueError:
        choices = ", ".join(profile.value for profile in Environment)
        raise ValueError(f"FALL_ENVIRONMENT deve ser um destes valores: {choices}") from None
    return Settings(environment=environment)
