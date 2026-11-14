"""Price-path utilities over trades (exact times) and carried-forward quotes."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from prooflag.ingest.models import Trade


@dataclass(frozen=True)
class Quote:
    ts: datetime
    bid: float | None
    ask: float | None


@dataclass(frozen=True)
class Capacity:
    trades: int
    contracts: float
    cost: float
    gross_profit: float
    fees: float

    @property
    def net_profit(self) -> float:
        return self.gross_profit - self.fees


def last_trade_at(trades: Sequence[Trade], t: datetime, max_age: timedelta) -> Trade | None:
    """Last trade at or before ``t`` and not older than ``max_age`` (trades sorted by time)."""
    i = bisect_right([x.ts for x in trades], t)
    if i == 0:
        return None
    tr = trades[i - 1]
    return tr if t - tr.ts <= max_age else None


def ask_at(quotes: Sequence[Quote], t: datetime, max_age: timedelta) -> float | None:
    """YES ask from the latest quote at or before ``t`` (carry-forward, <= max_age old)."""
    i = bisect_right([q.ts for q in quotes], t)
    if i == 0:
        return None
    q = quotes[i - 1]
    return q.ask if t - q.ts <= max_age else None


def first_cross(
    trades: Sequence[Trade],
    level: float,
    *,
    sustained: bool,
    start: datetime | None = None,
    end: datetime | None = None,
) -> Trade | None:
    """First trade at or above ``level`` inside [start, end]. With ``sustained`` the price must
    stay at or above ``level`` for every later trade in the window (a lone spike does not count)."""
    window = [
        t for t in trades if (start is None or t.ts >= start) and (end is None or t.ts <= end)
    ]
    if not sustained:
        return next((t for t in window if t.price >= level), None)
    answer: Trade | None = None
    for t in reversed(window):
        if t.price >= level:
            answer = t
        else:
            break
    return answer


def price_at_offsets(
    trades: Sequence[Trade],
    t_doc: datetime,
    offsets: Sequence[timedelta],
    *,
    close: datetime | None,
    max_age: timedelta,
) -> dict[timedelta, float | str | None]:
    """Last traded price at t_doc + offset. 'NA' when the offset lies beyond the market close (the
    market no longer trades; this is not a zero)."""
    out: dict[timedelta, float | str | None] = {}
    for off in offsets:
        t = t_doc + off
        if close is not None and t > close:
            out[off] = "NA"
            continue
        lt = last_trade_at(trades, t, max_age)
        out[off] = None if lt is None else lt.price
    return out


def capacity(
    trades: Sequence[Trade],
    t_from: datetime,
    t_to: datetime,
    ceiling: float,
    fee_fn: Callable[[float, float], float],
) -> Capacity:
    """What a taker could have captured by buying YES in every trade inside [t_from, t_to] that
    printed below ``ceiling`` (each trade treated as one order for fees)."""
    n = contracts = cost = gross = fees = 0.0
    for t in trades:
        if t.ts < t_from or t.ts > t_to or t.price >= ceiling:
            continue
        n += 1
        contracts += t.count
        cost += t.count * t.price
        gross += t.count * (1.0 - t.price)
        fees += fee_fn(t.count, t.price)
    return Capacity(int(n), contracts, cost, gross, fees)
