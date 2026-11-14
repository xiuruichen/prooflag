"""Shared scheduling helpers: per-source backoff and poll logging (poll_log table)."""

from __future__ import annotations

from datetime import datetime, timedelta

from prooflag.store.db import Db


def backoff_due(
    db: Db, source: str, base: timedelta, now: datetime, *, cap: timedelta = timedelta(minutes=15)
) -> bool:
    """Is the next attempt for ``source`` due? After a success: ``base`` after the last attempt.
    After consecutive failures the interval is 2, 4, 8 ... minutes, capped at max(base, cap): it
    grows past a small base (a 30 s fast cadence must still back off) yet retries a large base
    (an hourly catalog) sooner than its normal interval. A dead source is not hammered and a
    healthy one keeps its own schedule."""
    rows = db.conn.execute(
        "select ts, ok from poll_log where source=? order by id desc limit 12", (source,)
    ).fetchall()
    if not rows:
        return True
    fails = 0
    for r in rows:
        if r["ok"]:
            break
        fails += 1
    last = datetime.fromisoformat(rows[0]["ts"])
    interval = base if fails == 0 else min(timedelta(minutes=2**fails), max(base, cap))
    return now - last >= interval


def has_ok_poll(db: Db, source: str) -> bool:
    return (
        db.conn.execute(
            "select 1 from poll_log where source=? and ok=1 limit 1", (source,)
        ).fetchone()
        is not None
    )


def log_poll(
    db: Db,
    now: datetime,
    source: str,
    *,
    ok: bool,
    items: int,
    latency_ms: int,
    err: str | None = None,
) -> None:
    db.conn.execute(
        "insert into poll_log(source, ts, ok, latency_ms, items, err) values (?,?,?,?,?,?)",
        (source, now.isoformat(), int(ok), latency_ms, items, err),
    )
