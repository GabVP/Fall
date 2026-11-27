"""Contexto de proprietário obrigatório para operações sobre dados privados."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class OwnerScope:
    """Identidade validada da sessão, fornecida pela fronteira de autenticação."""

    user_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, UUID):
            raise TypeError("O proprietário deve ser identificado por UUID.")
