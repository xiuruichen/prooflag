from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from prooflag.edge.cases import (
    analyze_market,
    bucket_of,
    summarize_weeks,
)
from prooflag.edge.eo import ET, EoDoc, parse_rule
from prooflag.edge.fees import kalshi_taker_fee
from prooflag.edge.prices import Quote
from prooflag.ingest.models import Trade

D = date
RULE_TXT = (
    "If the President signs above {n} executive orders during Oct 18, 2026 to Oct 24, 2026, "
    "then the market resolves to Yes."
)


def utc(d, h=0, mi=0):  # type: ignore[no-untyped-def]
    return datetime(2026, 10, d, h, mi, tzinfo=UTC)


def eo(num, sign_d, pub_d, pi):  # type: ignore[no-untyped-def]
    return EoDoc(num, f"d{num}", D(2026, 10, sign_d), D(2026, 10, pub_d), pi)


def tr(ts, price, count=100.0, i=[0]):  # type: ignore[no-untyped-def]  # noqa: B006
    i[0] += 1
    return Trade(ts, price, count, "yes", f"id{i[0]}")


# EO 1 signed 10/19 posted (PI) 10/20 15:00Z, published 10/21; EO 2 signed 10/22, PI 10/23 15:00Z.
EOS = [
    eo(1, 19, 21, utc(20, 15)),
    eo(2, 22, 24, utc(23, 15)),
    eo(3, 26, 28, utc(27, 15)),  # outside the window
]


def market(n, result="yes", close=None):  # type: ignore[no-untyped-def]
    return {
        "ticker": f"KXEOWEEK-26OCT24-{n}",
        "event_ticker": "KXEOWEEK-26OCT24",
        "result": result,
        "rules_primary": RULE_TXT.format(n=n),
        "open_time": "2026-10-17T14:00:00Z",
        "close_time": (close or utc(24, 14, 30)).isoformat().replace("+00:00", "Z"),
    }


def test_price_that_lagged_the_posting_gives_positive_lag_and_profit() -> None:
    # '>1' needs 2 EOs: decided by EO 2 (PI 10/23 15:00Z). Price stays 0.40 until 20 min later.
    trades = [
        tr(utc(18, 10), 0.35),
        tr(utc(23, 14), 0.40),
        tr(utc(23, 15, 20), 0.97),
        tr(utc(23, 16), 0.98),
    ]
    quotes = [Quote(utc(23, 14), 0.38, 0.42), Quote(utc(23, 15, 20), 0.95, 0.97)]
    c = analyze_market(market(1), parse_rule(RULE_TXT.format(n=1)), EOS, trades, quotes)
    assert c.validated and c.implied == "yes" and c.eligible
    pi = c.pi
    assert pi.t_doc == utc(23, 15) and pi.deciding_number == 2
    assert pi.price_at == 0.40
    assert pi.lag90_minutes == pytest.approx(20.0)
    assert not pi.price_led
    assert pi.ask == 0.42  # quote carried forward to t_doc + 2 min
    assert pi.pnl_per_contract == pytest.approx(0.58 - kalshi_taker_fee(100, 0.42) / 100)
    assert pi.pnl_free_per_contract == pytest.approx(0.58)
    assert pi.capacity.trades == 0  # trades after the buy are all >= the 0.95 ceiling
    assert pi.bucket90 == "pi_to_pub"


def test_price_that_led_the_posting_has_negative_lag_and_is_flagged() -> None:
    trades = [tr(utc(20, 9), 0.30), tr(utc(21, 12), 0.96), tr(utc(22, 12), 0.99)]  # before EO 2
    quotes = [Quote(utc(21, 12), 0.95, 0.97)]
    c = analyze_market(market(1), parse_rule(RULE_TXT.format(n=1)), EOS, trades, quotes)
    assert c.pi.price_led and c.pi.lag90_minutes < 0
    # first sustained cross (10/21 12:00Z) precedes the deciding EO's signing day (10/22 ET)
    assert c.pi.bucket90 == "before_signing"


def test_no_implied_markets_are_validated_but_not_eligible() -> None:
    trades = [tr(utc(20, 12), 0.5)]
    c = analyze_market(market(5, result="no"), parse_rule(RULE_TXT.format(n=5)), EOS, trades, [])
    assert c.validated and c.implied == "no" and not c.eligible


def test_mismatch_between_computed_and_recorded_result_is_reported() -> None:
    c = analyze_market(market(5, result="yes"), parse_rule(RULE_TXT.format(n=5)), EOS, [], [])
    assert c.implied == "no" and c.validated is False and not c.eligible


def test_exactly_rules_are_validated_only() -> None:
    txt = (
        "If the President signs exactly 2 Executive Orders during Oct 18, 2026 to Oct 24, "
        "2026, then the market resolves to Yes."
    )
    m = {**market(2), "rules_primary": txt}
    c = analyze_market(m, parse_rule(txt), EOS, [], [])
    assert c.implied == "yes" and c.validated and not c.eligible


def test_offsets_after_the_close_are_na() -> None:
    trades = [tr(utc(23, 14), 0.40), tr(utc(23, 15, 10), 0.97)]
    close = utc(23, 15, 30)
    c = analyze_market(
        market(1, close=close),
        parse_rule(RULE_TXT.format(n=1)),
        EOS,
        trades,
        [Quote(utc(23, 14), 0.38, 0.42)],
    )
    offs = {k.total_seconds(): v for k, v in c.pi.offsets.items()}
    assert offs[60.0] == 0.40 and offs[900.0] == 0.97
    assert offs[3600.0] == "NA" and offs[21600.0] == "NA"


def test_posting_after_the_close_is_not_eligible() -> None:
    c = analyze_market(market(1, close=utc(23, 12)), parse_rule(RULE_TXT.format(n=1)), EOS, [], [])
    assert c.implied == "yes" and not c.eligible and "closed" in c.excluded_reason


def test_missing_ask_excludes_pnl_but_keeps_other_metrics() -> None:
    trades = [tr(utc(23, 14), 0.40), tr(utc(23, 15, 20), 0.97)]
    c = analyze_market(market(1), parse_rule(RULE_TXT.format(n=1)), EOS, trades, [])
    assert c.pi.ask is None and c.pi.pnl_per_contract is None and c.pi.lag90_minutes == 20.0


def test_bucket_boundaries() -> None:
    sign = datetime(2026, 10, 22, 0, 0, tzinfo=ET)
    pi, pub = utc(23, 15), datetime(2026, 10, 24, 6, 0, tzinfo=ET)
    assert bucket_of(None, sign, pi, pub) == "never"
    assert bucket_of(sign - timedelta(seconds=1), sign, pi, pub) == "before_signing"
    assert bucket_of(sign, sign, pi, pub) == "signing_to_pi"
    assert bucket_of(pi, sign, pi, pub) == "pi_to_pub"
    assert bucket_of(pub, sign, pi, pub) == "after_pub"


def test_week_summary_uses_weeks_as_the_independent_unit() -> None:
    trades_lag = [tr(utc(23, 14), 0.40), tr(utc(23, 15, 20), 0.97)]
    q = [Quote(utc(23, 14), 0.38, 0.42)]
    cases = []
    for n in (0, 1):  # two markets of the SAME week
        cases.append(
            analyze_market(market(n), parse_rule(RULE_TXT.format(n=n)), EOS, trades_lag, q)
        )
    s = summarize_weeks(cases)
    assert s.n_markets_eligible == 2 and s.n_weeks_usable == 1  # one independent week
    assert s.weeks[0].week == "KXEOWEEK-26OCT24"


def test_price_based_buy_sensitivity_is_reported_when_no_ask_exists() -> None:
    trades = [tr(utc(23, 14), 0.40), tr(utc(23, 15, 1), 0.60)]
    c = analyze_market(market(1), parse_rule(RULE_TXT.format(n=1)), EOS, trades, [])
    assert c.pi.ask is None and c.pi.pnl_per_contract is None
    assert c.pi.price_buy == 0.60  # last trade at t_doc + 2 min
    assert c.pi.pnl_price_per_contract == pytest.approx(0.40 - kalshi_taker_fee(100, 0.60) / 100)


def test_summary_counts_weeks_with_a_usable_ask_and_price_based_ci() -> None:
    trades = [tr(utc(23, 14), 0.40), tr(utc(23, 15, 1), 0.60)]
    cases = [
        analyze_market(market(n), parse_rule(RULE_TXT.format(n=n)), EOS, trades, []) for n in (0, 1)
    ]
    s = summarize_weeks(cases)
    assert s.n_weeks_with_ask == 0 and s.pnl_ci is None
    assert s.n_weeks_with_price_buy == 1 and s.pnl_price_ci is not None


def test_a_week_is_usable_only_with_a_trade_before_the_posting() -> None:
    # Pre-registered: usable = a Yes-implied market with prices around t_pi. Trades that all occur
    # AFTER the posting give a first-0.90 time but no price at the posting: not usable.
    trades = [tr(utc(23, 16), 0.97), tr(utc(23, 17), 0.98)]
    c = analyze_market(market(1), parse_rule(RULE_TXT.format(n=1)), EOS, trades, [])
    assert c.eligible and c.pi.first90 is not None and c.pi.price_at is None
    assert summarize_weeks([c]).n_weeks_usable == 0
