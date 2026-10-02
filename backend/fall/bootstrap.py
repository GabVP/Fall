"""Composição compartilhada pelos processos HTTP e worker."""

from dataclasses import dataclass

from fall.config import Settings, load_settings


@dataclass(frozen=True)
class Runtime:
    """Contexto da aplicação; futuros serviços serão montados aqui."""

    settings: Settings


def build_runtime(settings: Settings | None = None) -> Runtime:
    return Runtime(settings=settings if settings is not None else load_settings())
