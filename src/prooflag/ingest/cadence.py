"""Price-snapshot cadence: fast inside the EDGAR window (weekdays, ET), slow otherwise."""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _parse(s: str) -> time:
    m = _HHMM.match(s)
    if not m:
        raise ValueError(f"expected HH:MM, got {s!r}")
    return time(int(m.group(1)), int(m.group(2)))


class Cadence:
    """US federal holidays are not special-cased (EDGAR is closed then); the fast cadence on a
    holiday only costs a few extra requests."""

    def __init__(
        self,
        window_start: str = "06:00",
        window_end: str = "22:00",
        fast_minutes: float = 5,
        slow_minutes: float = 30,
    ) -> None:
        self.start = _parse(window_start)
        self.end = _parse(window_end)
        if self.start >= self.end:
            raise ValueError("window_start must be before window_end")
        self.fast = timedelta(minutes=fast_minutes)
        self.slow = timedelta(minutes=slow_minutes)

    def in_window(self, now: datetime) -> bool:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        local = now.astimezone(ET)
        return local.weekday() < 5 and self.start <= local.time() < self.end

    def interval(self, now: datetime) -> timedelta:
        return self.fast if self.in_window(now) else self.slow

    def is_due(self, last_run: datetime | None, now: datetime) -> bool:
        return last_run is None or now - last_run >= self.interval(now)
