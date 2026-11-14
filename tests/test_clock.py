from datetime import UTC, datetime, timedelta

from prooflag.clock import FixedClock, SystemClock


def test_fixed_clock_advances_only_when_told() -> None:
    t0 = datetime(2026, 5, 31, 23, 59, tzinfo=UTC)
    c = FixedClock(t0)
    assert c.now() == t0
    c.advance(timedelta(minutes=2))
    assert c.now() == datetime(2026, 6, 1, 0, 1, tzinfo=UTC)


def test_system_clock_is_timezone_aware_utc() -> None:
    assert SystemClock().now().tzinfo is UTC
