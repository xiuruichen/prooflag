from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest
from ingest_helpers import body_of

from prooflag.ingest.kalshi import KalshiSource
from prooflag.ingest.models import RawMarket
from prooflag.ingest.polymarket import PolymarketSource
from prooflag.ingest.tagging import (
    assign_cluster,
    is_meaningful,
    is_review_candidate,
    tag_market,
)

NOW = datetime(2026, 11, 13, tzinfo=UTC)


def kalshi_markets() -> list[RawMarket]:
    src = KalshiSource(None, "x")  # type: ignore[arg-type]
    out = []
    for ev in (
        body_of("kalshi_events_page1.json")["events"]
        + body_of("kalshi_events_eo_settled.json")["events"]
    ):
        if ev["category"] == "Sports":
            continue
        out += [m for m in (src._safe_parse(ev, mk) for mk in ev["markets"]) if m]
    return out


def poly_markets() -> list[RawMarket]:
    src = PolymarketSource(None, "g", "c", clock=lambda: NOW)  # type: ignore[arg-type]
    out = []
    for ev in body_of("poly_events_page1.json")["events"]:
        out += [m for m in (src._safe_parse(ev, mk) for mk in ev["markets"]) if m]
    return out


def names(tags) -> set[str]:  # type: ignore[no-untyped-def]
    return {t.tag for t in tags}


def test_weekly_eo_is_identified_by_series_and_is_the_primary_eval_source() -> None:
    eo = [m for m in kalshi_markets() if m.series_ticker == "KXEOWEEK"]
    assert eo
    for m in eo:
        t = names(tag_market(m))
        assert {"weekly_eo", "primary_eval"} <= t
    # A market whose *title* merely mentions executive orders is not the series.
    fake = copy.deepcopy(eo[0])
    fake.series_ticker = "KXSOMETHINGELSE"
    assert "weekly_eo" not in names(tag_market(fake))


def test_every_regex_tag_span_is_verbatim_in_the_rule_text() -> None:
    checked = 0
    for m in kalshi_markets() + poly_markets():
        text = " ".join([m.rules_primary, m.rules_secondary, m.resolution_source])
        for t in tag_market(m):
            if t.tag in {"sec", "court", "fed_register", "press_release"}:
                assert t.span and t.span in text, (m.market_id, t)
                checked += 1
    assert checked > 0


def test_fomc_markets_are_tagged_and_never_watch_candidates() -> None:
    fomc = [m for m in kalshi_markets() + poly_markets() if "fomc" in names(tag_market(m))]
    assert any(m.venue == "kalshi" for m in fomc) and any(m.venue == "polymarket" for m in fomc)
    for m in fomc:
        m.vol24_usd_est = 1e9
        assert not is_review_candidate(tag_market(m), m, min_usd=1000)


def test_ipo_family_cluster_spans_both_venues_and_both_issuers() -> None:
    ipo = [m for m in kalshi_markets() + poly_markets() if "ipo_family" in names(tag_market(m))]
    venues = {m.venue for m in ipo}
    assert venues == {"kalshi", "polymarket"}
    assert {assign_cluster(m).cluster_id for m in ipo} == {"issuer_ipo_family"}
    anth = [m for m in ipo if "anthropic" in (m.title + (m.event_title or "")).lower()]
    openai = [m for m in ipo if "openai" in (m.title + (m.event_title or "")).lower()]
    assert anth and openai  # both issuers land in the one correlated cluster


def test_weekly_eo_cluster_is_per_week_and_settled_weeks_get_their_own() -> None:
    eo = [m for m in kalshi_markets() if m.series_ticker == "KXEOWEEK"]
    ids = {m.event_id: assign_cluster(m).cluster_id for m in eo}
    assert len(set(ids.values())) == len(ids) >= 2  # one cluster per week/event
    open_week = next(m for m in eo if m.event_id == "KXEOWEEK-26NOV14")
    assert assign_cluster(open_week).cluster_id == "weekly_eo:2026-11-14"
    siblings = [m for m in eo if m.event_id == "KXEOWEEK-26NOV14"]
    assert {assign_cluster(m).cluster_id for m in siblings} == {"weekly_eo:2026-11-14"}


def test_default_cluster_is_the_event_so_brackets_count_once() -> None:
    fed = [m for m in poly_markets() if m.event_title and m.event_title.startswith("Fed Decision")]
    assert len(fed) >= 2
    assert len({assign_cluster(m).cluster_id for m in fed}) == 1
    other = next(m for m in poly_markets() if m.event_id != fed[0].event_id)
    assert assign_cluster(other).cluster_id != assign_cluster(fed[0]).cluster_id


def test_eo_second_term_is_tagged_and_clustered_together() -> None:
    m = RawMarket(
        venue="kalshi",
        market_id="KXEOTRUMPTERM-29JAN20-300",
        title="t",
        rules_primary="Executive Order published in the Federal Register.",
        series_ticker="KXEOTRUMPTERM",
        event_id="KXEOTRUMPTERM-29JAN20",
    )
    assert {"eo_second_term", "fed_register"} <= names(tag_market(m))
    assert assign_cluster(m).cluster_id == "eo_second_term"


@pytest.mark.parametrize(
    ("venue", "vol_usd", "oi", "liq", "expected"),
    [
        ("kalshi", 1000.0, None, None, True),
        ("kalshi", 999.99, 5_000_000.0, None, False),  # OI alone never counts
        ("kalshi", 0.0, 9e9, None, False),
        ("polymarket", 999.0, None, 1e9, False),  # liquidity is not volume
        ("polymarket", 1500.0, None, 0.0, True),
        ("kalshi", None, 9e9, None, False),
    ],
)
def test_meaningful_filter(venue, vol_usd, oi, liq, expected) -> None:  # type: ignore[no-untyped-def]
    m = RawMarket(
        venue=venue,
        market_id="x",
        title="t",
        rules_primary="r",
        vol24_usd_est=vol_usd,
        open_interest_contracts=oi,
        liquidity_usd=liq,
    )
    assert is_meaningful(m, 1000.0) is expected


def test_review_candidate_rules() -> None:
    sec = RawMarket(
        venue="polymarket",
        market_id="a",
        title="t",
        rules_primary="as filed with the SEC in Form S-1",
        vol24_usd_est=50.0,
    )
    assert not is_review_candidate(tag_market(sec), sec, 1000.0)  # tagged but not meaningful
    sec.vol24_usd_est = 5000.0
    assert is_review_candidate(tag_market(sec), sec, 1000.0)
    press = RawMarket(
        venue="polymarket",
        market_id="c",
        title="t",
        rules_primary="see the official announcement",
        vol24_usd_est=9e6,
    )
    assert not is_review_candidate(tag_market(press), press, 1000.0)  # press_release alone: no
    eo = RawMarket(
        venue="kalshi",
        market_id="b",
        title="t",
        rules_primary="r",
        series_ticker="KXEOWEEK",
        event_id="KXEOWEEK-26NOV14",
        vol24_usd_est=0.0,
    )
    # Weekly EO is covered by the allow-list series entry, not by the regex review queue.
    assert not is_review_candidate(tag_market(eo), eo, 1000.0)
