from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from prooflag.edge.fees import (
    kalshi_taker_fee,
    pnl_buy_yes_hold,
    polymarket_taker_fee,
)
from prooflag.edge.prices import (
    Quote,
    ask_at,
    capacity,
    first_cross,
    last_trade_at,
    price_at_offsets,
)
from prooflag.edge.stats import (
    MIN_WEEKS,
    bootstrap_mean_ci,
    quantile,
    verdict,
)
from prooflag.ingest.models import Trade

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def tr(minutes: float, price: float, count: float = 10.0, tid: str = "") -> Trade:
    return Trade(T0 + timedelta(minutes=minutes), price, count, "yes", tid or f"t{minutes}")


# -- fees ---------------------------------------------------------------------------------
def test_kalshi_fee_known_values_and_cent_rounding() -> None:
    assert kalshi_taker_fee(100, 0.5) == 1.75
    assert kalshi_taker_fee(100, 0.99) == 0.07  # 0.0693 rounds UP to the cent
    assert kalshi_taker_fee(1, 0.5) == 0.02  # 0.0175 -> 0.02
    assert kalshi_taker_fee(100, 1.0) == 0.0 and kalshi_taker_fee(0, 0.5) == 0.0
    assert kalshi_taker_fee(100, 0.5, multiplier=2.0) == 3.5
    assert kalshi_taker_fee(100, 0.3) == 1.47  # float noise must not push this to 1.48


@given(st.floats(1, 5000), st.floats(0.01, 0.99))
def test_kalshi_fee_is_bounded(count: float, price: float) -> None:
    fee = kalshi_taker_fee(count, price)
    assert 0 <= fee <= 0.07 * count * 0.25 + 0.01 + 1e-9


def test_polymarket_fee_formula_rounding_and_minimum() -> None:
    assert polymarket_taker_fee(100, 0.5, rate=0.04) == 1.0
    assert polymarket_taker_fee(100, 1.0, rate=0.04) == 0.0
    assert polymarket_taker_fee(0.001, 0.5, rate=0.04) == 0.00001  # minimum when positive
    assert polymarket_taker_fee(10, 0.37, rate=0.04) == round(10 * 0.04 * 0.37 * 0.63, 5)
    assert polymarket_taker_fee(100, 0.5, rate=0.0) == 0.0


def test_pnl_buy_yes_hold() -> None:
    assert pnl_buy_yes_hold(100, 0.80, yes=True, fee=0.5) == pytest.approx(100 * 0.2 - 0.5)
    assert pnl_buy_yes_hold(100, 0.80, yes=False, fee=0.5) == pytest.approx(-80.0 - 0.5)


# -- prices -------------------------------------------------------------------------------
def test_last_trade_at_respects_time_and_staleness() -> None:
    trades = [tr(0, 0.5), tr(10, 0.6), tr(20, 0.9)]
    assert last_trade_at(trades, T0 + timedelta(minutes=15), timedelta(hours=1)).price == 0.6  # type: ignore[union-attr]
    assert last_trade_at(trades, T0 + timedelta(minutes=10), timedelta(hours=1)).price == 0.6  # type: ignore[union-attr]
    assert last_trade_at(trades, T0 - timedelta(minutes=1), timedelta(hours=1)) is None
    assert last_trade_at(trades, T0 + timedelta(hours=30), timedelta(hours=24)) is None  # stale


def test_ask_at_carries_quotes_forward_within_the_staleness_limit() -> None:
    quotes = [Quote(T0, 0.4, 0.5), Quote(T0 + timedelta(hours=2), 0.6, 0.7)]
    assert ask_at(quotes, T0 + timedelta(hours=1), timedelta(hours=24)) == 0.5
    assert ask_at(quotes, T0 + timedelta(hours=3), timedelta(hours=24)) == 0.7
    assert ask_at(quotes, T0 - timedelta(hours=1), timedelta(hours=24)) is None
    assert ask_at(quotes, T0 + timedelta(hours=60), timedelta(hours=24)) is None
    assert ask_at([Quote(T0, 0.4, None)], T0, timedelta(hours=1)) is None


def test_first_cross_sustained_ignores_a_lone_spike() -> None:
    trades = [tr(0, 0.3), tr(1, 0.95), tr(2, 0.5), tr(3, 0.92), tr(4, 0.97)]
    touch = first_cross(trades, 0.90, sustained=False)
    sustained = first_cross(trades, 0.90, sustained=True)
    assert touch is not None and touch.trade_id == "t1"
    assert sustained is not None and sustained.trade_id == "t3"  # stays >= 0.90 from here
    assert first_cross([tr(0, 0.95), tr(1, 0.4)], 0.90, sustained=True) is None
    assert first_cross([], 0.90, sustained=True) is None


def test_first_cross_respects_the_window() -> None:
    trades = [tr(0, 0.95), tr(10, 0.96), tr(20, 0.97)]
    got = first_cross(
        trades,
        0.90,
        sustained=True,
        start=T0 + timedelta(minutes=5),
        end=T0 + timedelta(minutes=15),
    )
    assert got is not None and got.trade_id == "t10"


def test_price_at_offsets_marks_beyond_close_as_na_not_zero() -> None:
    trades = [tr(0, 0.4), tr(2, 0.6), tr(70, 0.9)]
    out = price_at_offsets(
        trades,
        T0,
        [timedelta(minutes=1), timedelta(minutes=15), timedelta(hours=1), timedelta(hours=6)],
        close=T0 + timedelta(hours=2),
        max_age=timedelta(hours=24),
    )
    assert out[timedelta(minutes=1)] == 0.4
    assert out[timedelta(minutes=15)] == 0.6
    assert out[timedelta(hours=1)] == 0.6
    assert out[timedelta(hours=6)] == "NA"  # market closed before this offset


def test_capacity_counts_only_cheap_trades_in_the_window_net_of_fees() -> None:
    trades = [tr(1, 0.5, 100), tr(3, 0.96, 500), tr(5, 0.8, 50), tr(30, 0.7, 10)]
    cap = capacity(
        trades,
        T0 + timedelta(minutes=2),
        T0 + timedelta(minutes=10),
        0.95,
        lambda c, p: kalshi_taker_fee(c, p),
    )
    assert cap.contracts == 50 and cap.trades == 1  # only the 0.80 trade qualifies
    assert cap.cost == pytest.approx(40.0)
    assert cap.gross_profit == pytest.approx(50 * 0.2)
    assert cap.fees == pytest.approx(kalshi_taker_fee(50, 0.8))
    assert cap.net_profit == pytest.approx(10.0 - cap.fees)


# -- stats --------------------------------------------------------------------------------
def test_quantile_linear_interpolation() -> None:
    xs = [1.0, 2.0, 3.0, 4.0]
    assert quantile(xs, 0.5) == 2.5 and quantile(xs, 0.0) == 1.0 and quantile(xs, 1.0) == 4.0
    assert quantile(xs, 0.25) == pytest.approx(1.75)
    assert quantile([7.0], 0.9) == 7.0


def test_bootstrap_ci_is_deterministic_and_brackets_the_mean() -> None:
    xs = [0.01, -0.02, 0.03, 0.0, 0.05, -0.01, 0.02, 0.04, 0.0, 0.01]
    a = bootstrap_mean_ci(xs, resamples=2000, seed=1)
    b = bootstrap_mean_ci(xs, resamples=2000, seed=1)
    assert a == b
    mean, lo, hi = a
    assert lo <= mean <= hi and mean == pytest.approx(sum(xs) / len(xs))
    assert bootstrap_mean_ci([0.5] * 8, resamples=500, seed=1) == (0.5, 0.5, 0.5)


def v(**kw):  # type: ignore[no-untyped-def]
    base = dict(
        n_weeks=20,
        share_ge90_at_pi=0.2,
        pnl_ci=(0.05, 0.02, 0.09),
        median_lag_minutes=30.0,
        median_capacity_usd=50.0,
    )
    base.update(kw)
    return verdict(**base)


def test_verdict_insufficient_when_too_few_weeks() -> None:
    assert v(n_weeks=MIN_WEEKS - 1).label == "INSUFFICIENT DATA"


def test_verdict_no_edge_when_price_already_moved_before_the_posting() -> None:
    assert v(share_ge90_at_pi=0.7).label == "NO SPEED EDGE"
    assert v(share_ge90_at_pi=0.69).label == "EDGE POSSIBLE"


def test_verdict_no_edge_when_pnl_upper_bound_is_tiny() -> None:
    assert v(pnl_ci=(0.005, -0.01, 0.02)).label == "NO SPEED EDGE"
    assert v(pnl_ci=(0.01, -0.01, 0.0201)).label == "INSUFFICIENT DATA"  # inconclusive


def test_verdict_edge_possible_needs_lag_and_capacity_and_positive_lower_bound() -> None:
    assert v().label == "EDGE POSSIBLE"
    assert v(median_lag_minutes=4.9).label == "INSUFFICIENT DATA"
    assert v(pnl_ci=(0.05, 0.0, 0.09)).label == "INSUFFICIENT DATA"  # lower bound must be > 0


def test_verdict_edge_without_tradable_size_is_no_speed_edge() -> None:
    r = v(median_capacity_usd=9.99)
    assert r.label == "NO SPEED EDGE"
    assert any("capacity" in reason for reason in r.reasons)


def test_verdict_no_edge_takes_precedence_over_edge_possible() -> None:
    r = v(share_ge90_at_pi=0.9, pnl_ci=(0.05, 0.02, 0.09))  # edge criteria hold AND price led
    assert r.label == "NO SPEED EDGE"


def test_verdict_without_any_pnl_estimate_does_not_invent_a_pnl_criterion() -> None:
    r = verdict(
        n_weeks=12,
        share_ge90_at_pi=0.2,
        pnl_ci=None,
        median_lag_minutes=60.0,
        median_capacity_usd=50.0,
    )
    assert r.label == "INSUFFICIENT DATA"
    assert any("P&L" in reason for reason in r.reasons)
    # the share rule alone can still decide NO SPEED EDGE
    r2 = verdict(
        n_weeks=12,
        share_ge90_at_pi=0.9,
        pnl_ci=None,
        median_lag_minutes=60.0,
        median_capacity_usd=50.0,
    )
    assert r2.label == "NO SPEED EDGE" and not any("upper 95%" in x for x in r2.reasons)


def test_kalshi_fee_by_series_fee_type() -> None:
    from prooflag.edge.fees import UnsupportedFeeTypeError, kalshi_fee

    # standard quadratic: taker = round_up(0.07 x C x P x (1-P)), makers pay nothing
    assert kalshi_fee("quadratic", 1.0, 100, 0.5) == 1.75
    assert kalshi_fee("quadratic", 1.0, 100, 0.5, role="maker") == 0.0
    # maker-fee series: maker = round_up(0.0175 x C x P x (1-P)) = 0.4375 -> 0.44
    assert kalshi_fee("quadratic_with_maker_fees", 1.0, 100, 0.5) == 1.75
    assert kalshi_fee("quadratic_with_maker_fees", 1.0, 100, 0.5, role="maker") == 0.44
    assert kalshi_fee("quadratic", 2.0, 100, 0.5) == 3.5  # series multiplier scales the fee
    assert kalshi_fee("fee_free", 1.0, 100, 0.5) == 0.0
    # flat / unknown types are NOT guessed
    with pytest.raises(UnsupportedFeeTypeError):
        kalshi_fee("flat", 1.0, 100, 0.5)
    with pytest.raises(UnsupportedFeeTypeError):
        kalshi_fee("something_new", 1.0, 100, 0.5)
    with pytest.raises(ValueError):
        kalshi_fee("quadratic", 1.0, 100, 0.5, role="broker")
