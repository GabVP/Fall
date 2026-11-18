"""Tipos para futuras tabelas; nenhuma tabela funcional é criada aqui."""

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.types import TypeDecorator

from fall.domain.money import Currency, require_decimal
from fall.domain.time import as_utc


class DecimalAmount(TypeDecorator):
    """NUMERIC exato sem escala global; precisão de cada recurso será explícita."""

    impl = Numeric
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else require_decimal(value)


class CurrencyCode(TypeDecorator):
    impl = String(3)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, Currency):
            raise TypeError("Moeda exige Currency ISO 4217")
        return value.code

    def process_result_value(self, value, dialect):
        return None if value is None else Currency(value)


class UTCInstant(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else as_utc(value)

    def process_result_value(self, value, dialect):
        return None if value is None else as_utc(value)
