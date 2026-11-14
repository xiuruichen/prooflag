from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from prooflag.edge.e2 import E2Market, EventResult, analyze_event, overall
from prooflag.ingest.models import Trade

T = datetime(2026, 11, 20, 15, 0, 0, tzinfo=UTC)
NOFEE = lambda c, p: 0.0  # noqa: E731


def tr(minutes: float, price: float, count: float = 100.0, i: list[int] = [0]) -> Trade:  # noqa: B006
    i[0] += 1
    return Trade(T + timedelta(minutes=minutes), price, count, "yes", f"t{i[0]}")


def pre(n: int = 12, price: float = 0.5) -> list[Trade]:
    """n trades in the 24 h before the filing."""
    return [tr(-600 + k * 10, price) for k in range(n)]


def mk(
    mid: str,
    trades: list[Trade],
    *,
    direction: str = "yes",
    venue: str = "kalshi",
    source: str = "trades",
) -> E2Market:
    return E2Market(mid, venue, direction, sorted(trades, key=lambda t: t.ts), source, NOFEE, None)


def event(markets: list[E2Market]) -> EventResult:
    return analyze_event("A", T, markets)


def moved_market(mid: str) -> E2Market:  # price already reflects the outcome within 5 minutes
    return mk(mid, [*pre(), tr(-2, 0.60), tr(3, 0.95), tr(10, 0.97)])


def slow_market(mid: str) -> E2Market:  # barely moves for an hour, big capacity later
    return mk(mid, [*pre(), tr(-1, 0.40), tr(30, 0.50), tr(90, 0.70, 500.0), tr(200, 0.97)])


def test_moved_by_5min_when_price_reaches_090_within_five_minutes() -> None:
    r = event([moved_market(f"m{i}") for i in range(3)])
    m = r.markets[0]
    assert m.p0 == 0.5 and m.pA == 0.60 and m.p5 == 0.95 and m.moved
    assert r.share_moved == 1.0 and r.signal == "DEAD"


def test_moved_by_5min_when_half_the_remaining_distance_is_covered() -> None:
    # p0 = 0.40 (60 min before), p5 = 0.72: (0.72-0.40)/(1-0.40) = 0.533 >= 0.5
    m = mk("a", [*pre(price=0.40), tr(-61, 0.40), tr(2, 0.72)])
    r = event([m, m, m])
    assert r.markets[0].moved
    just_short = mk("b", [*pre(price=0.40), tr(-61, 0.40), tr(2, 0.69)])  # 0.483 < 0.5
    assert not event([just_short] * 3).markets[0].moved


def test_a_move_before_the_filing_counts() -> None:
    m = mk("a", [*pre(price=0.30), tr(-90, 0.30), tr(-30, 0.92), tr(-1, 0.93), tr(4, 0.94)])
    r = event([m, m, m]).markets[0]
    assert r.pA >= 0.90 and r.pre_priced and r.moved


def test_direction_no_markets_are_analysed_in_the_resolved_direction() -> None:
    # YES price falls from 0.5 to 0.04 => NO price rises to 0.96
    m = mk("n", [*pre(), tr(-1, 0.5), tr(3, 0.04), tr(10, 0.03)], direction="no")
    r = event([m, m, m]).markets[0]
    assert r.p0 == pytest.approx(0.5) and r.p5 == pytest.approx(0.96) and r.moved


def test_usability_thresholds_kalshi_trades_and_polymarket_points() -> None:
    few = mk("few", [*pre(9), tr(3, 0.9)])
    assert not event([few]).markets[0].usable
    ok = mk("ok", [*pre(10), tr(3, 0.9)])
    assert event([ok]).markets[0].usable
    poly_few = mk("pf", [*pre(19), tr(3, 0.9)], venue="polymarket")
    assert not event([poly_few]).markets[0].usable
    poly_ok = mk("po", [*pre(20), tr(3, 0.9)], venue="polymarket")
    assert event([poly_ok]).markets[0].usable


def test_snapshot_resolution_markets_never_count_toward_the_event() -> None:
    snaps = [mk(f"s{i}", [*pre(), tr(3, 0.95)], source="snapshot") for i in range(5)]
    r = event([*snaps, moved_market("m1"), moved_market("m2")])
    assert r.n_usable == 2 and r.signal == "INSUFFICIENT"  # only 2 full-resolution markets
    assert all(m.source == "snapshot" and not m.counted for m in r.markets[:5])


def test_fewer_than_three_usable_markets_is_insufficient() -> None:
    assert event([moved_market("a"), moved_market("b")]).signal == "INSUFFICIENT"


def test_alive_signal_needs_low_move_share_lag_and_capacity() -> None:
    r = event([slow_market(f"s{i}") for i in range(3)])
    assert r.share_moved == 0.0 and r.median_lag_minutes >= 5
    assert r.capacity_total >= 100 and r.signal == "ALIVE"
    # same shape but too little capacity: INCONCLUSIVE
    small = [
        mk(f"x{i}", [*pre(), tr(-1, 0.40), tr(30, 0.50, 1.0), tr(90, 0.96, 5.0), tr(200, 0.97)])
        for i in range(3)
    ]
    assert event(small).signal == "INCONCLUSIVE"


def test_a_market_that_never_reaches_090_counts_as_an_infinite_lag() -> None:
    m = mk("never", [*pre(), tr(-1, 0.40), tr(30, 0.60), tr(90, 0.70, 500.0)])
    r = event([m, m, m])
    assert r.median_lag_minutes == float("inf") and r.signal == "ALIVE"


def test_depth_is_notional_traded_within_two_cents_of_the_pre_filing_price() -> None:
    m = mk(
        "d",
        [
            *pre(),
            tr(-1, 0.40),
            tr(1, 0.41, 100.0),
            tr(5, 0.42, 200.0),
            tr(10, 0.45, 999.0),
            tr(61, 0.40, 999.0),
        ],
    )
    r = event([m, m, m])
    # pA = 0.40; trades at 0.41 and 0.42 qualify (0.45 is too far, 61 min is too late)
    per_market = 100 * 0.41 + 200 * 0.42
    assert r.depth_total == pytest.approx(3 * per_market)


def test_fees_reduce_capacity_via_the_market_fee_function() -> None:
    t = [*pre(), tr(-1, 0.40), tr(30, 0.50, 1000.0), tr(200, 0.97)]
    free = E2Market("f", "kalshi", "yes", sorted(t, key=lambda x: x.ts), "trades", NOFEE, None)
    paid = E2Market(
        "p", "kalshi", "yes", sorted(t, key=lambda x: x.ts), "trades", lambda c, p: 10.0, None
    )
    a, b = analyze_event("A", T, [free, free, free]), analyze_event("A", T, [paid, paid, paid])
    assert a.capacity_total - b.capacity_total == pytest.approx(30.0)


# -- overall verdict and pursue --------------------------------------------------------------
def ev(signal: str, depth: float = 0.0, name: str = "A") -> EventResult:
    return EventResult(
        name=name,
        t_doc=T,
        markets=[],
        n_usable=3,
        share_moved=0.0,
        median_lag_minutes=10.0,
        capacity_total=500.0,
        depth_total=depth,
        signal=signal,
    )


@pytest.mark.parametrize(
    ("a", "b", "verdict"),
    [
        ("DEAD", None, "SPEED THESIS DEAD"),
        ("DEAD", "DEAD", "SPEED THESIS DEAD"),
        ("DEAD", "INCONCLUSIVE", "SPEED THESIS DEAD"),
        ("DEAD", "ALIVE", "MIXED"),
        ("ALIVE", "INCONCLUSIVE", "SPEED THESIS ALIVE (provisional)"),
        ("ALIVE", "ALIVE", "SPEED THESIS ALIVE (provisional)"),
        ("ALIVE", None, "SPEED THESIS ALIVE (provisional)"),
        ("INCONCLUSIVE", "INCONCLUSIVE", "INCONCLUSIVE"),
        ("INSUFFICIENT", "INSUFFICIENT", "INSUFFICIENT DATA"),
        (None, None, "INSUFFICIENT DATA"),
        ("INSUFFICIENT", None, "INSUFFICIENT DATA"),
        ("INSUFFICIENT", "DEAD", "SPEED THESIS DEAD"),
    ],
)
def test_overall_verdict_table(a, b, verdict) -> None:  # type: ignore[no-untyped-def]
    events = {"A": ev(a) if a else None, "B": ev(b, name="B") if b else None}
    assert overall(events).verdict == verdict


def test_pursue_requires_an_alive_event_with_at_least_300_dollars_of_depth() -> None:
    assert overall({"A": ev("ALIVE", depth=300.0), "B": None}).pursue is True
    assert overall({"A": ev("ALIVE", depth=299.99), "B": None}).pursue is False
    assert overall({"A": ev("DEAD", depth=9999.0), "B": None}).pursue is False
    # MIXED: pursue only for the document type whose event is ALIVE and deep enough
    mixed = overall({"A": ev("DEAD", depth=9999.0), "B": ev("ALIVE", depth=400.0, name="B")})
    assert mixed.verdict == "MIXED" and mixed.pursue is False  # verdict is not ALIVE => no


def test_exactly_half_the_remaining_distance_counts_as_moved_despite_float_error() -> None:
    # (0.6-0.2)/(1-0.2) == 0.49999999999999994 in floating point
    m = mk("f", [*pre(price=0.2), tr(-61, 0.2), tr(2, 0.6)])
    assert event([m, m, m]).markets[0].moved


def test_depth_band_edge_is_inclusive_for_no_direction_float_error() -> None:
    # direction no: pA = 1 - 0.90 = 0.0999..., a trade at 1 - 0.88 = 0.12 is exactly 2 cents away
    m = mk("g", [*pre(price=0.9), tr(-1, 0.90), tr(5, 0.88, 100.0)], direction="no")
    assert event([m, m, m]).depth_total == pytest.approx(3 * 100 * 0.12)
