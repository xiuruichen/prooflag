from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from prooflag.ingest.cadence import Cadence

ET = ZoneInfo("America/New_York")
C = Cadence()  # 06:00-22:00 ET weekdays, 5 / 30 minutes


def et(y: int, mo: int, d: int, h: int, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=ET).astimezone(UTC)


@pytest.mark.parametrize(
    ("when", "minutes"),
    [
        (et(2026, 11, 13, 10), 5),  # Friday mid-morning
        (et(2026, 11, 13, 5, 59), 30),  # before the window
        (et(2026, 11, 13, 6, 0), 5),  # window start inclusive
        (et(2026, 11, 13, 21, 59), 5),
        (et(2026, 11, 13, 22, 0), 30),  # window end exclusive
        (et(2026, 11, 14, 10), 30),  # Saturday
        (et(2026, 11, 15, 10), 30),  # Sunday
        (et(2026, 11, 16, 6, 0), 5),  # Monday
    ],
)
def test_interval_by_et_wall_clock(when: datetime, minutes: int) -> None:
    assert C.interval(when) == timedelta(minutes=minutes)


def test_window_follows_et_across_dst() -> None:
    # 2026-03-09 is EDT (UTC-4): 06:00 ET = 10:00Z. 2026-03-06 is EST: 06:00 ET = 11:00Z.
    assert C.interval(datetime(2026, 3, 9, 9, 59, tzinfo=UTC)) == timedelta(minutes=30)
    assert C.interval(datetime(2026, 3, 9, 10, 0, tzinfo=UTC)) == timedelta(minutes=5)
    assert C.interval(datetime(2026, 3, 6, 10, 59, tzinfo=UTC)) == timedelta(minutes=30)
    assert C.interval(datetime(2026, 3, 6, 11, 0, tzinfo=UTC)) == timedelta(minutes=5)


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        C.interval(datetime(2026, 1, 1, 12))


def test_custom_window_and_intervals() -> None:
    c = Cadence(window_start="09:30", window_end="16:00", fast_minutes=2, slow_minutes=15)
    assert c.interval(et(2026, 11, 13, 9, 30)) == timedelta(minutes=2)
    assert c.interval(et(2026, 11, 13, 16, 0)) == timedelta(minutes=15)


def test_bad_window_rejected() -> None:
    with pytest.raises(ValueError):
        Cadence(window_start="22:00", window_end="06:00")
    with pytest.raises(ValueError):
        Cadence(window_start="6am")


def test_due_logic() -> None:
    now = et(2026, 11, 13, 10)
    assert C.is_due(None, now)
    assert not C.is_due(now - timedelta(minutes=4, seconds=59), now)
    assert C.is_due(now - timedelta(minutes=5), now)
    off = et(2026, 11, 14, 10)
    assert not C.is_due(off - timedelta(minutes=29), off)
    assert C.is_due(off - timedelta(minutes=30), off)


@given(
    st.datetimes(
        min_value=datetime(2020, 1, 1), max_value=datetime(2035, 1, 1), timezones=st.just(UTC)
    )
)
def test_interval_property(ts: datetime) -> None:
    local = ts.astimezone(ET)
    in_window = local.weekday() < 5 and 6 <= local.hour < 22
    assert C.interval(ts) == timedelta(minutes=5 if in_window else 30)
