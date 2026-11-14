"""APScheduler wiring for ingest. The full `prooflag run` process is assembled later (U6b)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apscheduler.schedulers.base import BaseScheduler


def schedule(scheduler: BaseScheduler, run_due: Callable[[], Any], tick_seconds: int = 60) -> None:
    """One idempotent tick per minute; the service decides what is due (5/30-minute snapshot
    cadence by EDGAR window, hourly catalog), so a missed tick never double-runs."""
    scheduler.add_job(
        run_due,
        "interval",
        seconds=tick_seconds,
        id="ingest_tick",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
