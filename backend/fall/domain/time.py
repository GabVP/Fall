"""Instantes em UTC e interpretação explícita do horário de São Paulo."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def as_utc(instant: datetime) -> datetime:
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("Instantes exigem fuso explícito")
    return instant.astimezone(timezone.utc)


def in_sao_paulo(instant: datetime) -> datetime:
    return as_utc(instant).astimezone(SAO_PAULO)


def sao_paulo_to_utc(local_time: datetime, *, fold: int | None = None) -> datetime:
    """Interpreta relógio local sem fuso; rejeita lacunas e exige fold em duplicatas.

    fold=0 escolhe a primeira ocorrência; fold=1 escolhe a segunda durante
    retorno do horário de verão. A política de reagendamento cabe ao worker.
    """
    if local_time.tzinfo is not None:
        raise ValueError("Horário local deve ser informado sem fuso")
    if fold not in (None, 0, 1):
        raise ValueError("fold deve ser 0 ou 1")
    candidates = {}
    for occurrence in (0, 1):
        candidate = local_time.replace(tzinfo=SAO_PAULO, fold=occurrence)
        utc = as_utc(candidate)
        if in_sao_paulo(utc).replace(tzinfo=None) == local_time:
            candidates[occurrence] = utc
    if not candidates:
        raise ValueError("Horário local inexistente em America/Sao_Paulo")
    if len(set(candidates.values())) > 1 and fold is None:
        raise ValueError("Horário local ambíguo; informe fold")
    return candidates[0 if fold is None else fold]
