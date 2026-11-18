"""Representação monetária sem conversão cambial nem arredondamento implícito."""

from dataclasses import dataclass
from decimal import Decimal

from iso4217 import Currency


def require_decimal(value: Decimal) -> Decimal:
    """Exige Decimal finito; construa valores a partir de texto, nunca float."""
    if not isinstance(value, Decimal):
        raise TypeError("Valores monetários exigem Decimal")
    if not value.is_finite():
        raise ValueError("Valores monetários devem ser finitos")
    return value


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        require_decimal(self.amount)
        if not isinstance(self.currency, Currency):
            raise TypeError("Moeda exige Currency ISO 4217")
