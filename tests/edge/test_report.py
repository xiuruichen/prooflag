from __future__ import annotations

from datetime import UTC, datetime

from prooflag.edge.report import ts


def test_ts_prints_utc_wall_clock_for_aware_datetimes_in_other_zones() -> None:
    et_time = datetime.fromisoformat("2025-10-17T11:15:00.000-04:00")  # = 15:15 UTC
    assert ts(et_time) == "2025-10-17 15:15Z"
    assert ts(datetime(2026, 6, 1, 12, 0, 16, tzinfo=UTC)) == "2026-06-01 12:00Z"
    assert ts(None) == "n/a"
