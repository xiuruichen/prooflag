"""Descriptive price reaction of a market cluster around EDGAR filing acceptance times (E1)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from prooflag.edge.prices import last_trade_at
from prooflag.edge.stats import quantile
from prooflag.ingest.models import Trade

REACTION_OFFSETS: tuple[tuple[str, timedelta], ...] = (
    ("-1 h", timedelta(hours=-1)),
    ("+1 min", timedelta(minutes=1)),
    ("+15 min", timedelta(minutes=15)),
    ("+1 h", timedelta(hours=1)),
    ("+6 h", timedelta(hours=6)),
    ("+24 h", timedelta(hours=24)),
)
STALE = timedelta(hours=6)  # thin markets: a price older than 6 h is not used (descriptive study)


@dataclass(frozen=True)
class ReactionRow:
    label: str
    median_change: float | None  # price(t + offset) - price(t), median over markets
    n: int
    mean_abs_change: float | None = None  # mean |change|: a median of 0 can hide large moves


@dataclass(frozen=True)
class Reaction:
    n_markets: int
    rows: list[ReactionRow]


def reaction(
    series: Mapping[str, Sequence[Trade]],
    t: datetime,
    offsets: Sequence[tuple[str, timedelta]] = REACTION_OFFSETS,
) -> Reaction:
    """Median price change from the filing time. Markets with no price at the filing time are
    skipped; an offset with no price inside the staleness window contributes nothing."""
    base: dict[str, float] = {}
    for mid, trades in series.items():
        lt = last_trade_at(list(trades), t, STALE)
        if lt is not None:
            base[mid] = lt.price
    rows: list[ReactionRow] = []
    for label, off in offsets:
        changes: list[float] = []
        for mid, p0 in base.items():
            target = t + off
            trades = list(series[mid])
            if off > timedelta(0):
                # a price after the filing must come from a trade after it
                lt = last_trade_at(trades, target, STALE)
                if lt is None or lt.ts <= t:
                    continue
            else:
                lt = last_trade_at(trades, target, STALE)
                if lt is None:
                    continue
            changes.append(lt.price - p0)
        rows.append(
            ReactionRow(
                label,
                quantile(changes, 0.5) if changes else None,
                len(changes),
                sum(abs(c) for c in changes) / len(changes) if changes else None,
            )
        )
    return Reaction(len(base), rows)
