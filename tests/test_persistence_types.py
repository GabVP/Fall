"""Roundtrip dos tipos em PostgreSQL real, em tabela sintética descartável."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, insert, select, text
from sqlalchemy.exc import StatementError

from fall.domain.money import Currency
from fall.domain.time import SAO_PAULO
from fall.persistence.database import create_database_engine
from fall.persistence.types import CurrencyCode, DecimalAmount, UTCInstant


def test_postgresql_preserves_decimal_currency_and_utc(disposable_database) -> None:
    engine = create_database_engine(disposable_database)
    table = Table(
        "conventions_probe", MetaData(),
        Column("id", Integer, primary_key=True),
        Column("amount", DecimalAmount(), nullable=False),
        Column("currency", CurrencyCode(), nullable=False),
        Column("observed_at", UTCInstant(), nullable=False),
    )
    amount = Decimal("12345678901234567890.12345678901234567890")
    local_time = datetime(2018, 1, 15, 9, 30, tzinfo=SAO_PAULO)
    values = dict(id=1, amount=amount, currency=Currency.BRL, observed_at=local_time)
    try:
        table.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(insert(table).values(**values))
        with engine.connect() as connection:
            # A sessão tem fuso não UTC: o adaptador deve devolver UTC mesmo assim.
            connection.execute(text("SET TIME ZONE 'America/Sao_Paulo'"))
            row = connection.execute(select(table)).one()
            assert isinstance(row.amount, Decimal)
            assert row.amount == amount
            assert row.currency is Currency.BRL
            assert row.observed_at == datetime(2018, 1, 15, 11, 30, tzinfo=timezone.utc)
            assert row.observed_at.tzinfo is timezone.utc
            types = dict(connection.execute(text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'conventions_probe'"
            )).all())
            assert types["amount"] == "numeric"
            assert types["observed_at"] == "timestamp with time zone"

        for invalid in (
            {"amount": 0.1}, {"amount": Decimal("NaN")},
            {"currency": "ZZZ"}, {"observed_at": datetime(2026, 1, 1)},
        ):
            with pytest.raises(StatementError):
                with engine.begin() as connection:
                    connection.execute(insert(table).values(**(values | {"id": 2} | invalid)))
    finally:
        engine.dispose()
