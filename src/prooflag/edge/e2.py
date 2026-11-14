"""E2: pre-registered analysis of price reaction around a settling EDGAR filing.

Implements studies/e2/preregistration.md (original text + Amendment 1) exactly. Do not tune.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median

from prooflag.edge.prices import Capacity, capacity, first_cross, last_trade_at, price_at_offsets
from prooflag.ingest.models import Trade

STALE = timedelta(hours=24)
MIN_MARKETS = 3
MOVED_ABS = 0.90
MOVED_FRAC = 0.50
DEAD_SHARE = 0.70
ALIVE_SHARE = 0.30
ALIVE_LAG_MIN = 5.0
ALIVE_CAPACITY = 100.0
PURSUE_DEPTH = 300.0
DEPTH_BAND = 0.02
KALSHI_MIN_TRADES = 10
POLY_MIN_POINTS = 20
OFFSETS = (timedelta(minutes=1), timedelta(minutes=15), timedelta(hours=1), timedelta(hours=6))
FeeFn = Callable[[float, float], float]


@dataclass
class E2Market:
    market_id: str
    venue: str
    direction: str  # resolved direction: 'yes' or 'no' (A: implied yes)
    trades: list[Trade]  # YES-price trades, oldest first
    source: str  # 'trades' | 'clob' | 'snapshot'
    fee_fn: FeeFn
    close: datetime | None


@dataclass
class MarketResult:
    market_id: str
    source: str
    usable: bool
    counted: bool
    p0: float | None = None
    pA: float | None = None
    p5: float | None = None
    moved: bool = False
    pre_priced: bool = False
    lag_minutes: float | None = None  # None = never reached a sustained 0.90 in the data
    offsets: dict[timedelta, float | str | None] = field(default_factory=dict)
    capacity: Capacity = field(default_factory=lambda: Capacity(0, 0.0, 0.0, 0.0, 0.0))
    depth_usd: float = 0.0


@dataclass
class EventResult:
    name: str
    t_doc: datetime
    markets: list[MarketResult]
    n_usable: int
    share_moved: float
    median_lag_minutes: float
    capacity_total: float
    depth_total: float
    signal: str  # DEAD | ALIVE | INCONCLUSIVE | INSUFFICIENT


@dataclass
class Overall:
    verdict: str
    pursue: bool
    reasons: list[str]


def _direction_view(trades: Sequence[Trade], direction: str) -> list[Trade]:
    if direction == "yes":
        return list(trades)
    return [Trade(t.ts, 1.0 - t.price, t.count, t.taker_side, t.trade_id) for t in trades]


def _usable(m: E2Market, t_doc: datetime) -> bool:
    window = [t for t in m.trades if t_doc - STALE <= t.ts < t_doc]
    if m.venue == "polymarket":
        return len({(t.ts, t.price) for t in window}) >= POLY_MIN_POINTS
    return len(window) >= KALSHI_MIN_TRADES


def _analyze_market(m: E2Market, t_doc: datetime) -> MarketResult:
    usable = _usable(m, t_doc)
    counted = usable and m.source != "snapshot"
    r = MarketResult(m.market_id, m.source, usable, counted)
    if not usable:
        return r
    tr = _direction_view(m.trades, m.direction)
    p0t = last_trade_at(tr, t_doc - timedelta(minutes=60), STALE)
    pat = last_trade_at(tr, t_doc, STALE)
    p5t = last_trade_at(tr, t_doc + timedelta(minutes=5), STALE)
    r.p0 = None if p0t is None else p0t.price
    r.pA = None if pat is None else pat.price
    r.p5 = None if p5t is None else p5t.price
    if r.p5 is not None:
        r.moved = r.p5 >= MOVED_ABS or (
            r.p0 is not None
            and r.p0 < MOVED_ABS
            and (r.p5 - r.p0) / (1.0 - r.p0) >= MOVED_FRAC - 1e-9
        )
    r.pre_priced = r.pA is not None and r.pA >= MOVED_ABS
    sustained = first_cross(tr, MOVED_ABS, sustained=True, end=m.close)
    r.lag_minutes = None if sustained is None else (sustained.ts - t_doc).total_seconds() / 60
    r.offsets = price_at_offsets(tr, t_doc, OFFSETS, close=m.close, max_age=STALE)
    t_from = t_doc + timedelta(minutes=2)
    t_to = min(m.close, t_doc + STALE) if m.close else t_doc + STALE
    r.capacity = capacity(tr, t_from, t_to, 0.95, m.fee_fn)
    if r.pA is not None:
        lo, hi = r.pA - 1e-9, r.pA + DEPTH_BAND + 1e-9
        r.depth_usd = sum(
            t.count * t.price
            for t in tr
            if t_doc <= t.ts <= t_doc + timedelta(minutes=60) and lo <= t.price <= hi
        )
    return r


def analyze_event(name: str, t_doc: datetime, markets: Sequence[E2Market]) -> EventResult:
    results = [_analyze_market(m, t_doc) for m in markets]
    counted = [r for r in results if r.counted]
    n = len(counted)
    if n < MIN_MARKETS:
        return EventResult(name, t_doc, results, n, 0.0, float("nan"), 0.0, 0.0, "INSUFFICIENT")
    share = sum(r.moved for r in counted) / n
    lags = [float("inf") if r.lag_minutes is None else r.lag_minutes for r in counted]
    med = float(median(lags))
    cap = sum(r.capacity.net_profit for r in counted)
    depth = sum(r.depth_usd for r in counted)
    if share >= DEAD_SHARE:
        signal = "DEAD"
    elif share <= ALIVE_SHARE and med >= ALIVE_LAG_MIN and cap >= ALIVE_CAPACITY:
        signal = "ALIVE"
    else:
        signal = "INCONCLUSIVE"
    return EventResult(name, t_doc, results, n, share, med, cap, depth, signal)


def overall(events: dict[str, EventResult | None]) -> Overall:
    obs = {k: e for k, e in events.items() if e is not None}
    signals = {k: e.signal for k, e in obs.items()}
    dead = [k for k, s in signals.items() if s == "DEAD"]
    alive = [k for k, s in signals.items() if s == "ALIVE"]
    reasons = [
        f"event {k}: {e.signal} (share moved {e.share_moved:.0%}, n={e.n_usable}, "
        f"median lag {e.median_lag_minutes:.1f} min, capacity ${e.capacity_total:,.0f}, "
        f"depth ${e.depth_total:,.0f})"
        for k, e in obs.items()
    ]
    if not obs or all(s == "INSUFFICIENT" for s in signals.values()):
        verdict = "INSUFFICIENT DATA"
    elif dead and alive:
        verdict = "MIXED"
    elif dead:
        verdict = "SPEED THESIS DEAD"
    elif alive:
        verdict = "SPEED THESIS ALIVE (provisional)"
    else:
        verdict = "INCONCLUSIVE"
    pursue = verdict.startswith("SPEED THESIS ALIVE") and any(
        obs[k].depth_total >= PURSUE_DEPTH for k in alive
    )
    return Overall(verdict, pursue, reasons)
