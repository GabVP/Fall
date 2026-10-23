"""Contratos mínimos consumidos pelos casos de uso, sem dependência de adaptadores."""

from datetime import datetime
from typing import Protocol, TypeVar


Key = TypeVar("Key", contravariant=True)
Entity = TypeVar("Entity")


class Repository(Protocol[Key, Entity]):
    """Lê por identidade e salva; a unidade de trabalho define o commit externo.

    Repositórios concretos dos próximos módulos definirão escopo de proprietário
    e operações específicas. Ausência é None; falhas de persistência são erros.
    """

    def get(self, key: Key) -> Entity | None: ...

    def save(self, entity: Entity) -> None: ...


class Clock(Protocol):
    """Fornece um instante consciente de fuso, em UTC."""

    def now(self) -> datetime: ...
