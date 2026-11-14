"""Regression anchors on REAL recorded data (tests/fixtures/edge/e1_slice.json): 5 Kalshi weekly
executive-order markets with their trades, hourly candles and the Federal Register EOs of those
weeks. If the deciding-document logic or the metrics change, these known answers change."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from prooflag.edge.cases import analyze_market, eo_docs_from_inputs, summarize_weeks
from prooflag.edge.eo import parse_rule
from prooflag.edge.prices import Quote
from prooflag.ingest.models import Trade

SLICE = json.loads(
    (Path(__file__).resolve().parent.parent / "fixtures" / "edge" / "e1_slice.json").read_text(
        encoding="utf-8"
    )
)


def _cases() -> dict[str, object]:
    eos, stats = eo_docs_from_inputs(SLICE["eos"])
    assert stats["pi_missing"] == 0
    out = {}
    for m in SLICE["markets"]:
        trades = sorted(
            (
                Trade(datetime.fromisoformat(r[0]), float(r[1]), float(r[2]), r[3], r[4])
                for r in SLICE["trades"][m["ticker"]]
            ),
            key=lambda t: (t.ts, t.trade_id),
        )
        quotes = sorted(
            (
                Quote(datetime.fromisoformat(r[0]), r[1], r[2])
                for r in SLICE["candles"][m["ticker"]]
            ),
            key=lambda q: q.ts,
        )
        out[m["ticker"]] = analyze_market(m, parse_rule(m["rules_primary"]), eos, trades, quotes)
    return out


CASES = _cases()


def test_computed_results_match_the_venue_for_every_market() -> None:
    assert all(c.validated for c in CASES.values())  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("ticker", "decider", "t_pi_utc", "led", "bucket"),
    [
        (
            "KXEOWEEK-26OCT24-1",
            14438,
            datetime(2026, 10, 27, 15, 15, tzinfo=UTC),
            True,
            "signing_to_pi",
        ),
        (
            "KXEOWEEK-26OCT17-0",
            14436,
            datetime(2026, 10, 20, 15, 15, tzinfo=UTC),
            True,
            "signing_to_pi",
        ),
        ("KXEOWEEK-25OCT19", 14356, datetime(2025, 10, 17, 15, 15, tzinfo=UTC), False, "pi_to_pub"),
        ("KXEOWEEK-25NOV08", 14358, datetime(2025, 11, 6, 13, 45, tzinfo=UTC), False, "pi_to_pub"),
    ],
)
def test_deciding_eo_posting_time_and_bucket(ticker, decider, t_pi_utc, led, bucket) -> None:  # type: ignore[no-untyped-def]
    c = CASES[ticker]
    assert c.eligible  # type: ignore[attr-defined]
    assert c.pi.deciding_number == decider  # type: ignore[attr-defined]
    assert c.pi.t_doc.astimezone(UTC) == t_pi_utc  # type: ignore[attr-defined]
    assert c.pi.price_led is led  # type: ignore[attr-defined]
    assert c.pi.bucket90 == bucket  # type: ignore[attr-defined]


def test_october_2025_week_reacted_within_a_minute_of_public_inspection() -> None:
    c = CASES["KXEOWEEK-25OCT19"]
    assert c.pi.price_at == pytest.approx(0.82)  # type: ignore[attr-defined]
    assert c.pi.lag90_minutes == pytest.approx(0.7, abs=0.2)  # type: ignore[attr-defined]


def test_typical_week_price_led_the_posting_by_days() -> None:
    c = CASES["KXEOWEEK-26OCT24-1"]
    assert c.pi.lag90_minutes < -6000  # type: ignore[attr-defined]  # about 4.8 days before the posting


def test_week_summary_on_the_slice_counts_weeks_not_markets() -> None:
    s = summarize_weeks(list(CASES.values()))  # type: ignore[arg-type]
    assert s.n_weeks_usable == 4  # 26OCT24 (2 markets), 26OCT17, 25OCT19, 25NOV08
    assert s.n_markets_eligible == 5
    assert s.share_led == pytest.approx(0.5)  # 2 of 4 weeks led
