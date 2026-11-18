"""Adaptador do relógio de sistema para a porta Clock."""

from datetime import datetime, timezone


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)
