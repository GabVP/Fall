"""Caso de uso sintético executável só com portas e doubles em memória."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from fall.application.access import NewSession, UserCredentials
from fall.application.ports import Clock, Repository


@dataclass(frozen=True)
class Note:
    key: str
    updated_at: datetime


class MemoryNotes:
    def __init__(self):
        self.notes = {}

    def get(self, key: str) -> Note | None:
        return self.notes.get(key)

    def save(self, entity: Note) -> None:
        self.notes[entity.key] = entity


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 15, 12, tzinfo=timezone.utc)


def touch_note(key: str, notes: Repository[str, Note], clock: Clock) -> None:
    note = notes.get(key)
    if note is None:
        raise LookupError(key)
    notes.save(replace(note, updated_at=clock.now()))


def test_use_case_uses_injected_persistence_and_time() -> None:
    notes = MemoryNotes()
    assert notes.get("synthetic") is None
    notes.save(Note("synthetic", datetime(2025, 1, 1, tzinfo=timezone.utc)))
    touch_note("synthetic", notes, FixedClock())
    assert notes.get("synthetic").updated_at == FixedClock().now()


@pytest.mark.parametrize(
    "record",
    [
        UserCredentials(
            user_id=UUID(int=1),
            password_hash="credential-sentinel",
            is_active=True,
        ),
        NewSession(
            id=UUID(int=2),
            user_id=UUID(int=1),
            token_digest=b"credential-sentinel",
            created_at=FixedClock().now(),
            absolute_expires_at=FixedClock().now() + timedelta(hours=8),
        ),
    ],
)
def test_access_record_repr_omits_credentials(record: UserCredentials | NewSession) -> None:
    assert "credential-sentinel" not in repr(record)
