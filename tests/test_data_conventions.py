"""Convenções monetárias e temporais com dados exclusivamente sintéticos."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from fall.domain.money import Currency, Money
from fall.domain.time import as_utc, in_sao_paulo, sao_paulo_to_utc
from fall.integrations.clock import SystemClock


def test_decimal_retains_precision_without_implicit_rounding() -> None:
    first = Money(Decimal("0.10000001"), Currency("BRL"))
    second = Money(Decimal("0.20000002"), Currency.BRL)
    assert first.amount + second.amount == Decimal("0.30000003")


@pytest.mark.parametrize("amount", [0.1, 1, "0.1"])
def test_money_rejects_non_decimal(amount) -> None:
    with pytest.raises(TypeError):
        Money(amount, Currency.BRL)


@pytest.mark.parametrize("amount", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_money_rejects_nonfinite_decimal(amount) -> None:
    with pytest.raises(ValueError):
        Money(Decimal(amount), Currency.BRL)


def test_currency_requires_known_iso_code_and_no_implicit_conversion() -> None:
    with pytest.raises(ValueError):
        Currency("ZZZ")
    with pytest.raises(TypeError):
        Money(Decimal("1.00"), "BRL")
    assert Currency("USD").code == "USD"


@pytest.mark.parametrize("year,offset", [(2026, -3), (2018, -2)])
def test_local_time_respects_historical_timezone_rules(year, offset) -> None:
    local = datetime(year, 1, 15, 9, 30)
    utc = sao_paulo_to_utc(local)
    assert utc == datetime(year, 1, 15, 9 - offset, 30, tzinfo=timezone.utc)
    assert in_sao_paulo(utc).utcoffset() == timedelta(hours=offset)
    assert in_sao_paulo(utc).replace(tzinfo=None) == local


def test_naive_instant_and_nonexistent_local_time_are_rejected() -> None:
    with pytest.raises(ValueError, match="fuso"):
        as_utc(datetime(2026, 1, 15))
    with pytest.raises(ValueError, match="inexistente"):
        sao_paulo_to_utc(datetime(2018, 11, 4, 0, 30))


def test_repeated_local_time_requires_explicit_occurrence() -> None:
    local = datetime(2019, 2, 16, 23, 30)
    with pytest.raises(ValueError, match="ambíguo"):
        sao_paulo_to_utc(local)
    assert sao_paulo_to_utc(local, fold=1) - sao_paulo_to_utc(local, fold=0) == timedelta(hours=1)


def test_system_clock_returns_utc_instant() -> None:
    before = datetime.now(timezone.utc)
    instant = SystemClock().now()
    assert before <= instant <= datetime.now(timezone.utc)
    assert instant.tzinfo is timezone.utc
