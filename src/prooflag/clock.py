"""Injectable clock: core logic never calls datetime.now() directly (replay needs this)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._t = start

    def now(self) -> datetime:
        return self._t

    def advance(self, delta: timedelta) -> None:
        self._t += delta
