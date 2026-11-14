"""Real KalshiSource/PolymarketSource + service over recorded responses (no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from ingest_helpers import body_of, json_response

from prooflag.clock import FixedClock
from prooflag.config import Settings
from prooflag.ingest.factory import build_service
from prooflag.store.db import Db

T0 = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)  # Friday 10:00 ET
EMAIL = "private.person@example.org"


class Venues:
    """Routes by host like the real venues; serves recorded objects."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.kalshi_events = body_of("kalshi_events_page1.json")["events"]
        self.poly_events = body_of("poly_events_page1.json")["events"]

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        q = dict(req.url.params)
        host, path = req.url.host, req.url.path
        if host == "external-api.kalshi.com":
            if path.endswith("/events"):
                if q.get("series_ticker") == "KXEOWEEK" and q["status"] == "settled":
                    return json_response(body_of("kalshi_events_eo_settled.json"))
                if q.get("series_ticker"):
                    return json_response(body_of("kalshi_events_last_page_empty.json"))
                if q.get("cursor") == "CURSOR_PAGE2":
                    return json_response(body_of("kalshi_events_last_page_empty.json"))
                return json_response({"events": self.kalshi_events, "cursor": "CURSOR_PAGE2"})
            if path.endswith("/markets"):
                want = set(q["tickers"].split(","))
                ms = [m for ev in self.kalshi_events for m in ev["markets"] if m["ticker"] in want]
                return json_response({"markets": ms, "cursor": ""})
            if path.endswith("/candlesticks"):
                return json_response(body_of("kalshi_candlesticks.json"))
        if host == "gamma-api.polymarket.com":
            if path.endswith("/events/keyset"):
                if q.get("after_cursor") == "CURSOR_PAGE2":
                    return json_response(body_of("poly_events_last_page_empty.json"))
                return json_response({"events": self.poly_events, "next_cursor": "CURSOR_PAGE2"})
            if path.endswith("/markets"):
                want = set(req.url.params.get_list("condition_ids"))
                ms = [
                    m for ev in self.poly_events for m in ev["markets"] if m["conditionId"] in want
                ]
                return json_response([] if q.get("closed") == "true" else ms)
        if host == "clob.polymarket.com":
            return json_response(body_of("clob_prices_history.json"))
        raise AssertionError(f"unexpected request: {req.url}")


@pytest.fixture
def world(tmp_path: Path) -> Any:
    venues = Venues()
    settings = Settings(contact_email=EMAIL, data_dir=tmp_path, _env_file=None)
    db = Db(settings.db_path)
    db.migrate()
    clock = FixedClock(T0)
    svc = build_service(
        settings, db, clock, transport=httpx.MockTransport(venues), sleep=lambda _s: None
    )
    yield svc, db, venues, clock
    db.close()


def q(db: Db, sql: str, *a: Any) -> list[Any]:
    return db.conn.execute(sql, a).fetchall()


def test_full_cycle_over_recorded_venues(world) -> None:  # type: ignore[no-untyped-def]
    svc, db, venues, _clock = world
    res = svc.run_due()
    assert res.catalog_ran and res.snapshot_ran

    # Sports and combo markets never enter the store.
    sports_k = {
        m["ticker"]
        for ev in venues.kalshi_events
        if ev["category"] == "Sports"
        for m in ev["markets"]
    }
    stored = {r["market_id"] for r in q(db, "select market_id from markets")}
    assert sports_k and not sports_k & stored
    assert q(db, "select count(*) from markets where venue='polymarket'")[0][0] > 0

    # Weekly EO: ingested incl. settled weeks, tagged primary_eval, watched, one cluster per week.
    eo = q(db, "select * from markets where series_ticker='KXEOWEEK'")
    assert any(r["status"] == "settled" and r["result"] in ("yes", "no") for r in eo)
    assert all(r["watched"] == 1 for r in eo)
    assert len({r["cluster_id"] for r in eo}) >= 2
    assert q(db, "select count(*) from market_tags where tag='primary_eval'")[0][0] >= len(eo)

    # IPO family: one cluster across Kalshi and Polymarket.
    ipo = q(db, "select venue from markets where cluster_id='issuer_ipo_family'")
    assert {r["venue"] for r in ipo} == {"kalshi", "polymarket"}

    # FOMC markets are tagged but never watched, even when busy.
    fomc = q(
        db,
        "select m.watched from markets m join market_tags t using(venue, market_id)"
        " where t.tag='fomc'",
    )
    assert fomc and all(r["watched"] == 0 for r in fomc)

    # Snapshots exist for live watched markets (open EO weeks) with bid/ask/last.
    snaps = q(db, "select * from price_snapshots where source='snapshot'")
    assert snaps and all(s["ts_utc"] == T0.isoformat() for s in snaps)
    assert any(s["yes_bid"] is not None and s["yes_ask"] is not None for s in snaps)
    # History backfilled from the candlestick fixture (null trade prices kept as NULL).
    hist = q(db, "select * from price_snapshots where source='history'")
    assert hist and any(h["last_price"] is None for h in hist)


def test_requests_are_polite_generic_and_keyset_only(world) -> None:  # type: ignore[no-untyped-def]
    svc, _db, venues, _clock = world
    svc.run_due()
    assert venues.requests
    for r in venues.requests:
        blob = " ".join(f"{k}={v}" for k, v in r.headers.items()) + str(r.url)
        assert EMAIL not in blob  # contact email goes to the SEC only
        assert r.headers["user-agent"] == "Prooflag/0.1 (research; read-only)"
        assert "offset" not in dict(r.url.params)
        assert r.method == "GET"
    hosts = {r.url.host for r in venues.requests}
    assert hosts <= {"external-api.kalshi.com", "gamma-api.polymarket.com", "clob.polymarket.com"}
    gamma_events = [r for r in venues.requests if r.url.path.endswith("/events/keyset")]
    assert gamma_events and all(dict(r.url.params)["limit"] == "50" for r in gamma_events)


def test_second_cycle_is_idempotent_and_detects_a_silent_rule_edit(world) -> None:  # type: ignore[no-untyped-def]
    svc, db, venues, clock = world
    svc.run_due()
    n_versions = q(db, "select count(*) from market_versions")[0][0]
    n_markets = q(db, "select count(*) from markets")[0][0]
    # Silently edit the rules of one Kalshi EO market on the venue, then re-ingest.
    ev = next(e for e in venues.kalshi_events if e.get("series_ticker") == "KXEOWEEK")
    ev["markets"][0]["rules_secondary"] = (
        ev["markets"][0].get("rules_secondary") or ""
    ) + " EDITED."
    clock.advance(__import__("datetime").timedelta(minutes=61))
    svc.catalog_pass("kalshi")
    assert q(db, "select count(*) from markets")[0][0] == n_markets
    assert q(db, "select count(*) from market_versions")[0][0] == n_versions + 1
    assert q(db, "select count(*) from market_rule_changes")[0][0] == 1
