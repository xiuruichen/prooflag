from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from prooflag.edge.e2_dryrun import run
from prooflag.edge.e2_live import classify_market, find_events

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "e2" / "dryrun.json"


def d(day: int, h: int = 0) -> datetime:
    return datetime(2026, 11, day, h, tzinfo=UTC)


def test_no_events_before_effectiveness() -> None:
    assert find_events([("S-1", d(1)), ("FWP", d(12)), ("424B4", d(13))]) == (
        None,
        None,
    )  # B without A


def test_a_then_first_pricing_prospectus_after_it() -> None:
    rows = [
        ("S-1", d(1)),
        ("EFFECT", d(20, 15)),
        ("424B3", d(22)),
        ("424B4", d(21, 1)),
        ("424B4", d(19)),
    ]
    t_a, b = find_events(rows)
    assert t_a == d(20, 15) and b == ("424B4", d(21, 1))  # a 424B4 BEFORE A is ignored


def test_effect_without_pricing_yet() -> None:
    assert find_events([("EFFECT", d(20))]) == (d(20), None)


@pytest.mark.parametrize(
    ("venue", "series", "title", "expected"),
    [
        ("kalshi", "KXIPOANTHROPIC", "Will Anthropic announce an IPO by Dec 1?", "A"),
        (
            "kalshi",
            "KXANTHROPICLEADLEFT",
            "Will Goldman serve as lead-left underwriter on Anthropic's IPO?",
            "B",
        ),
        ("polymarket", None, "Will Anthropic's IPO valuation be between $1.0T and $1.25T?", "B"),
        ("polymarket", None, "Will Anthropic raise between $65B and $75B in its IPO?", "B"),
        ("polymarket", None, "What % of Anthropic will be sold in its IPO? 6-7%", "B"),
        (
            "polymarket",
            None,
            "Will Anthropic IPO by November 30?",
            None,
        ),  # settles on listing, not on B
        ("polymarket", None, "Will OpenAI's IPO valuation be above $1T?", None),
        ("kalshi", "KXEOWEEK", "Will the President sign more than 3 Executive Orders?", None),
    ],
)
def test_market_classification_uses_rule_wording_not_prices(venue, series, title, expected) -> None:  # type: ignore[no-untyped-def]
    assert classify_market(venue, series, title) == expected


def test_dry_run_reproduces_the_committed_fixture_exactly() -> None:
    """Regression anchor: the pre-registered code on real recorded data must not drift."""
    assert json.loads(json.dumps(run(), sort_keys=True)) == json.loads(
        FIXTURE.read_text(encoding="utf-8")
    )


def test_dry_run_exercises_the_expected_paths() -> None:
    d_ = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert d_["strategy"]["signal"] == "INSUFFICIENT"  # one market only: fewer than 3
    assert d_["strategy"]["markets"][0]["usable"] is True
    assert {e["signal"] for e in d_["anthropic_s1_dryrun_events"]} <= {
        "ALIVE",
        "DEAD",
        "INCONCLUSIVE",
    }
    assert all(e["n_usable_counted"] >= 3 for e in d_["anthropic_s1_dryrun_events"])
