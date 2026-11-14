"""Per-market and per-week analysis for the weekly executive-order markets (E1)."""

from __future__ import annotations

import gzip
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from prooflag.edge.eo import (
    ET,
    Basis,
    EoDoc,
    Rule,
    deciding_eo,
    dedupe,
    implied_result,
    in_window,
)
from prooflag.edge.fees import kalshi_taker_fee, pnl_buy_yes_hold
from prooflag.edge.prices import (
    Capacity,
    Quote,
    ask_at,
    capacity,
    first_cross,
    last_trade_at,
    price_at_offsets,
)
from prooflag.edge.stats import bootstrap_mean_ci, quantile, verdict, wilson
from prooflag.ingest.models import Trade

STALE = timedelta(hours=24)  # pre-registered: a quote/trade older than this is "no quote"
OFFSETS = (timedelta(minutes=1), timedelta(minutes=15), timedelta(hours=1), timedelta(hours=6))
BUY_DELAY = timedelta(minutes=2)
CEILING = 0.95
CONTRACTS = 100.0  # size used for fee computation (fees are per order)
BUCKETS = ("before_signing", "signing_to_pi", "pi_to_pub", "after_pub", "never")


@dataclass
class BasisResult:
    t_doc: datetime | None = None
    deciding_number: int | None = None
    price_at: float | None = None
    offsets: dict[timedelta, float | str | None] = field(default_factory=dict)
    first90_touch: datetime | None = None
    first90: datetime | None = None  # sustained
    first95: datetime | None = None  # sustained
    lag90_minutes: float | None = None
    lag95_minutes: float | None = None
    price_led: bool = False  # sustained >= 0.90 at or before t_doc
    bucket90: str = "never"
    ask: float | None = None
    pnl_per_contract: float | None = None
    pnl_free_per_contract: float | None = None
    # Sensitivity (not the pre-registered primary): buy at the LAST TRADE price at t_doc + 2 min,
    # i.e. ignoring the spread. Defined for more weeks than the ask-based P&L.
    price_buy: float | None = None
    pnl_price_per_contract: float | None = None
    capacity: Capacity = field(default_factory=lambda: Capacity(0, 0.0, 0.0, 0.0, 0.0))
    share_of_jump: float | None = None
    price_week_start: float | None = None


@dataclass
class MarketCase:
    ticker: str
    week: str
    rule_kind: str
    recorded: str
    implied: str
    validated: bool
    eligible: bool
    excluded_reason: str = ""
    close: datetime | None = None
    close_vs_pub_days: int | None = None
    pi: BasisResult = field(default_factory=BasisResult)
    pub: BasisResult = field(default_factory=BasisResult)


def bucket_of(t90: datetime | None, sign_start: datetime, t_pi: datetime, t_pub: datetime) -> str:
    if t90 is None:
        return "never"
    if t90 < sign_start:
        return "before_signing"
    if t90 < t_pi:
        return "signing_to_pi"
    if t90 < t_pub:
        return "pi_to_pub"
    return "after_pub"


def _analyze_basis(
    rule: Rule,
    window_eos: list[EoDoc],
    basis: Basis,
    trades: list[Trade],
    quotes: list[Quote],
    close: datetime | None,
    open_time: datetime | None,
) -> BasisResult:
    r = BasisResult()
    dec = deciding_eo(rule, window_eos, basis)
    if dec is None:
        return r
    t_doc = dec.posting_time(basis)
    assert t_doc is not None
    r.t_doc, r.deciding_number = t_doc, dec.number
    lt = last_trade_at(trades, t_doc, STALE)
    r.price_at = None if lt is None else lt.price
    r.offsets = price_at_offsets(trades, t_doc, OFFSETS, close=close, max_age=STALE)
    end = close
    s90 = first_cross(trades, 0.90, sustained=True, end=end)
    s95 = first_cross(trades, 0.95, sustained=True, end=end)
    t90 = first_cross(trades, 0.90, sustained=False, end=end)
    r.first90 = None if s90 is None else s90.ts
    r.first95 = None if s95 is None else s95.ts
    r.first90_touch = None if t90 is None else t90.ts
    if s90 is not None:
        r.lag90_minutes = (s90.ts - t_doc).total_seconds() / 60
    if s95 is not None:
        r.lag95_minutes = (s95.ts - t_doc).total_seconds() / 60
    r.price_led = s90 is not None and s90.ts <= t_doc
    sign_start = datetime.combine(dec.signing_date, time(0, 0), ET)
    t_pi = dec.pi_filed_at or t_doc
    r.bucket90 = bucket_of(r.first90, sign_start, t_pi, dec.t_pub)
    # naive rule: buy YES at the ask 2 minutes after the document, hold to settlement
    t_buy = t_doc + BUY_DELAY
    if close is None or t_buy <= close:
        r.ask = ask_at(quotes, t_buy, STALE)
    if r.ask is not None:
        fee = kalshi_taker_fee(CONTRACTS, r.ask)
        r.pnl_per_contract = pnl_buy_yes_hold(CONTRACTS, r.ask, yes=True, fee=fee) / CONTRACTS
        r.pnl_free_per_contract = pnl_buy_yes_hold(CONTRACTS, r.ask, yes=True, fee=0.0) / CONTRACTS
    if close is None or t_buy <= close:
        lt_buy = last_trade_at(trades, t_buy, STALE)
        if lt_buy is not None:
            r.price_buy = lt_buy.price
            fee_p = kalshi_taker_fee(CONTRACTS, lt_buy.price)
            r.pnl_price_per_contract = (
                pnl_buy_yes_hold(CONTRACTS, lt_buy.price, yes=True, fee=fee_p) / CONTRACTS
            )
    r.capacity = capacity(
        trades, t_buy, close or t_buy + timedelta(days=30), CEILING, kalshi_taker_fee
    )
    # share of the final jump already realized at the posting
    start_t = datetime.combine(rule.start, time(0, 0), ET)
    p0t = last_trade_at(trades, start_t, timedelta(days=30))
    first_after = next((t for t in trades if t.ts >= start_t), None)
    p0 = p0t.price if p0t is not None else (first_after.price if first_after else None)
    r.price_week_start = p0
    if p0 is not None and r.price_at is not None and p0 < 0.99:
        r.share_of_jump = (r.price_at - p0) / (1.0 - p0)
    return r


def analyze_market(
    market: dict[str, Any],
    rule: Rule | None,
    eos: list[EoDoc],
    trades: list[Trade],
    quotes: list[Quote],
) -> MarketCase:
    week = market["event_ticker"]
    assert rule is not None, f"unparsed rule for {market['ticker']}"
    docs = dedupe(eos)
    win = in_window(docs, rule.start, rule.end)
    implied = implied_result(rule, len(win))
    recorded = market["result"]
    close = _dt(market.get("close_time"))
    case = MarketCase(
        ticker=market["ticker"],
        week=week,
        rule_kind=rule.kind,
        recorded=recorded,
        implied=implied,
        validated=implied == recorded,
        eligible=False,
        close=close,
    )
    if rule.needed is None:
        case.excluded_reason = "exactly-N rule: validated only"
        return case
    if implied != "yes" or recorded != "yes":
        case.excluded_reason = "not Yes-implied" if implied == "no" else "result mismatch"
        return case
    open_time = _dt(market.get("open_time"))
    case.pi = _analyze_basis(rule, win, "pi", trades, quotes, close, open_time)
    case.pub = _analyze_basis(rule, win, "pub", trades, quotes, close, open_time)
    dec = deciding_eo(rule, win, "pub")
    if dec is not None and close is not None:
        case.close_vs_pub_days = (close.astimezone(ET).date() - dec.publication_date).days
    if case.pi.t_doc is None:
        case.excluded_reason = "no deciding posting time (public inspection missing)"
        return case
    if close is not None and case.pi.t_doc >= close:
        case.excluded_reason = "market closed before the public-inspection posting"
        return case
    case.eligible = True
    return case


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=UTC)


# -- aggregation ------------------------------------------------------------------------------
@dataclass
class WeekAgg:
    week: str
    n_markets: int
    led: bool
    mean_pnl: float | None
    mean_pnl_free: float | None
    mean_pnl_price: float | None
    median_lag90: float | None
    capacity_net: float
    buckets: dict[str, int]
    usable: bool


@dataclass
class Summary:
    weeks: list[WeekAgg]
    n_markets_eligible: int
    n_weeks_usable: int
    share_led: float
    share_led_ci: tuple[float, float]
    pnl_ci: tuple[float, float, float] | None
    pnl_free_ci: tuple[float, float, float] | None
    pnl_price_ci: tuple[float, float, float] | None
    lag_quartiles: tuple[float, float, float] | None
    capacity_median: float
    verdict_label: str = ""
    verdict_reasons: list[str] = field(default_factory=list)
    n_weeks_with_lag: int = 0
    n_weeks_with_ask: int = 0
    n_weeks_with_price_buy: int = 0


def summarize_weeks(cases: list[MarketCase], basis: Basis = "pi") -> Summary:
    by_week: dict[str, list[MarketCase]] = defaultdict(list)
    for c in cases:
        if c.eligible:
            by_week[c.week].append(c)
    weeks: list[WeekAgg] = []
    for week, cs in sorted(by_week.items()):
        res = [(c.pi if basis == "pi" else c.pub) for c in cs]
        # pre-registered: usable = a Yes-implied market with a price around the posting
        usable = any(r.price_at is not None for r in res)
        led_frac = sum(r.price_led for r in res) / len(res)
        pnls = [r.pnl_per_contract for r in res if r.pnl_per_contract is not None]
        pnls_free = [r.pnl_free_per_contract for r in res if r.pnl_free_per_contract is not None]
        pnls_price = [r.pnl_price_per_contract for r in res if r.pnl_price_per_contract is not None]
        lags = [r.lag90_minutes for r in res if r.lag90_minutes is not None]
        buckets: dict[str, int] = {b: 0 for b in BUCKETS}
        for r in res:
            buckets[r.bucket90] += 1
        weeks.append(
            WeekAgg(
                week=week,
                n_markets=len(cs),
                led=led_frac >= 0.5,
                mean_pnl=sum(pnls) / len(pnls) if pnls else None,
                mean_pnl_free=sum(pnls_free) / len(pnls_free) if pnls_free else None,
                mean_pnl_price=sum(pnls_price) / len(pnls_price) if pnls_price else None,
                median_lag90=quantile(lags, 0.5) if lags else None,
                capacity_net=sum(r.capacity.net_profit for r in res),
                buckets=buckets,
                usable=usable,
            )
        )
    usable_w = [w for w in weeks if w.usable]
    led = sum(w.led for w in usable_w)
    pnl_vals = [w.mean_pnl for w in usable_w if w.mean_pnl is not None]
    pnl_free_vals = [w.mean_pnl_free for w in usable_w if w.mean_pnl_free is not None]
    pnl_price_vals = [w.mean_pnl_price for w in usable_w if w.mean_pnl_price is not None]
    lag_vals = [w.median_lag90 for w in usable_w if w.median_lag90 is not None]
    caps = [w.capacity_net for w in usable_w]
    s = Summary(
        weeks=weeks,
        n_markets_eligible=sum(len(v) for v in by_week.values()),
        n_weeks_usable=len(usable_w),
        share_led=led / len(usable_w) if usable_w else 0.0,
        share_led_ci=wilson(led, len(usable_w)),
        pnl_ci=bootstrap_mean_ci(pnl_vals) if pnl_vals else None,
        pnl_free_ci=bootstrap_mean_ci(pnl_free_vals) if pnl_free_vals else None,
        pnl_price_ci=bootstrap_mean_ci(pnl_price_vals) if pnl_price_vals else None,
        n_weeks_with_ask=len(pnl_vals),
        n_weeks_with_price_buy=len(pnl_price_vals),
        lag_quartiles=(
            (quantile(lag_vals, 0.25), quantile(lag_vals, 0.5), quantile(lag_vals, 0.75))
            if lag_vals
            else None
        ),
        capacity_median=quantile(caps, 0.5) if caps else 0.0,
        n_weeks_with_lag=len(lag_vals),
    )
    v = verdict(
        n_weeks=s.n_weeks_usable,
        share_ge90_at_pi=s.share_led,
        pnl_ci=s.pnl_ci,
        median_lag_minutes=s.lag_quartiles[1] if s.lag_quartiles is not None else 0.0,
        median_capacity_usd=s.capacity_median,
    )
    s.verdict_label, s.verdict_reasons = v.label, v.reasons
    return s


# -- loading ----------------------------------------------------------------------------------
def read_gz(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def eo_docs_from_inputs(rows: list[dict[str, Any]]) -> tuple[list[EoDoc], dict[str, int]]:
    """Build EoDocs. PI posting time comes from the per-document API; if absent, from the epoch
    number after '?' in public_inspection_pdf_url (verified once against pdf_updated_at)."""
    stats = {"pi_api": 0, "pi_url_fallback": 0, "pi_missing": 0}
    out: list[EoDoc] = []
    for r in rows:
        pi_dt: datetime | None = None
        pi = r.get("pi") or {}
        if pi.get("filed_at"):
            pi_dt = datetime.fromisoformat(pi["filed_at"])
            stats["pi_api"] += 1
        elif r.get("pi_url_ts") and str(r["pi_url_ts"]).isdigit():
            pi_dt = datetime.fromtimestamp(int(r["pi_url_ts"]), UTC)
            stats["pi_url_fallback"] += 1
        else:
            stats["pi_missing"] += 1
        num = r.get("executive_order_number")
        out.append(
            EoDoc(
                int(num) if num not in (None, "") else None,
                r["document_number"],
                date.fromisoformat(r["signing_date"]),
                date.fromisoformat(r["publication_date"]),
                pi_dt,
            )
        )
    return out, stats
