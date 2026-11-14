"""Regression tests for defects found by the S2 live run and checker review."""

from __future__ import annotations

import copy
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fakes import FakeSource, mk
from ingest_helpers import body_of, json_response
from pydantic import ValidationError

from prooflag.config import Settings
from prooflag.ingest.kalshi import KalshiSource
from prooflag.ingest.polymarket import PolymarketSource
from prooflag.logging import configure_logging

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


# -- live finding: Polymarket markets with an empty conditionId merged into one row ----------
def poly(make_client: Any, handler: Any) -> PolymarketSource:
    return PolymarketSource(make_client(handler), "https://g.test", "https://c.test", lambda: NOW)


def poly_event() -> dict[str, Any]:
    ev = copy.deepcopy(
        next(
            e
            for e in body_of("poly_events_page1.json")["events"]
            if e["title"].startswith("Fed Decision")
        )
    )
    ev["tags"] = []
    return ev


def test_polymarket_market_without_an_id_is_skipped_and_counted(make_client) -> None:  # type: ignore[no-untyped-def]
    ev = poly_event()
    good = ev["markets"][0]
    no_id, missing = copy.deepcopy(good), copy.deepcopy(good)
    no_id["conditionId"] = ""
    del missing["conditionId"]
    ev["markets"] = [no_id, good, missing]

    def handler(req: httpx.Request) -> httpx.Response:
        if dict(req.url.params).get("after_cursor"):
            return json_response({"events": []})
        return json_response({"events": [ev], "next_cursor": "x"})

    src = poly(make_client, handler)
    ids = [m.market_id for m in src.iter_markets()]
    assert ids == [good["conditionId"]]  # unidentifiable markets never become a shared '' row
    assert src.parse_errors == 2


# -- checker 1: one malformed market must not kill the whole catalog pass --------------------
def test_kalshi_malformed_markets_are_skipped_not_fatal(make_client) -> None:  # type: ignore[no-untyped-def]
    ev = copy.deepcopy(body_of("kalshi_events_eo_settled.json")["events"][0])
    ok_count = len(ev["markets"])
    bad_time, no_ticker = copy.deepcopy(ev["markets"][0]), copy.deepcopy(ev["markets"][0])
    bad_time["ticker"] = "BAD-TIME"
    bad_time["close_time"] = "TBD"
    del no_ticker["ticker"]
    ev["markets"] += [bad_time, no_ticker]

    def handler(req: httpx.Request) -> httpx.Response:
        return json_response({"events": [ev], "cursor": ""})

    src = KalshiSource(make_client(handler), "https://k.test")
    got = [m.market_id for m in src.iter_markets(status="settled")]
    assert len(got) == ok_count + 1 and "BAD-TIME" in got  # unparsable date: kept, close_time None
    assert src.parse_errors == 1  # only the market without a ticker is skipped


def test_polymarket_malformed_market_is_skipped_not_fatal(make_client) -> None:  # type: ignore[no-untyped-def]
    ev = poly_event()
    bad_date = copy.deepcopy(ev["markets"][0])
    bad_date["conditionId"] = "0xBADDATE"
    bad_date["endDate"] = "garbage-date"
    n = len(ev["markets"])
    ev["markets"] += [bad_date, "not-a-dict", None]  # type: ignore[list-item]
    src = poly(make_client, lambda r: json_response({"events": [ev]}))
    got = {m.market_id: m for m in src.iter_markets()}
    assert len(got) == n + 1 and got["0xBADDATE"].close_time is None
    assert src.parse_errors == 2  # the two non-dict entries


def test_nan_and_comma_numbers_do_not_poison_volume(make_client) -> None:  # type: ignore[no-untyped-def]
    src = KalshiSource(make_client(lambda r: json_response({})), "https://k.test")
    ev = {"event_ticker": "E", "series_ticker": "S", "title": "t", "category": "Politics"}
    base = {
        "ticker": "E-1",
        "title": "m",
        "rules_primary": "r",
        "status": "active",
        "last_price_dollars": "0.5",
        "open_interest_fp": "1.00",
    }
    for bad in ("NaN", "inf", "1,234.00", ""):
        m = src.parse_market(ev, {**base, "volume_24h_fp": bad})
        assert m is not None and m.vol24_contracts is None and m.vol24_usd_est is None


def test_catalog_pass_counts_source_parse_errors(make_env) -> None:  # type: ignore[no-untyped-def]
    src = FakeSource("kalshi", [mk("A")])
    src.parse_errors = 3  # type: ignore[attr-defined]
    st = make_env(src).svc.catalog_pass("kalshi")
    assert st.errors == 3 and st.new == 1


# -- checker 2: no hammering after failures --------------------------------------------------
def test_failing_venue_backs_off_and_healthy_venue_keeps_its_own_schedule(make_env) -> None:  # type: ignore[no-untyped-def]
    class Down(FakeSource):
        def __init__(self) -> None:
            super().__init__("kalshi", [mk("A")])
            self.catalog_attempts = 0

        def iter_markets(self, **kw: Any):  # type: ignore[no-untyped-def]
            self.catalog_attempts += 1
            raise httpx.ConnectError("down")

    k = Down()
    p = FakeSource(
        "polymarket", [mk("0xP", venue="polymarket", series_ticker=None, token_ids={"yes": "TY"})]
    )
    env = make_env(k, p)
    env.allow_catalog()
    for _ in range(40):  # 40 one-minute ticks
        env.svc.run_due()
        env.clock.advance(timedelta(minutes=1))
    # Healthy Polymarket catalog ran once (hourly), not every minute.
    assert env.one("select count(*) from poll_log where source='catalog:polymarket'")[0] == 1
    # Failing Kalshi catalog: exponential backoff (2, 4, 8, 16 min ...), not once per minute.
    assert 2 <= k.catalog_attempts <= 6
    # Snapshots: healthy venue follows the 5-minute cadence (Friday 10:00 ET inside the window).
    n = env.one("select count(*) from poll_log where source='snapshot:polymarket' and ok=1")[0]
    assert 7 <= n <= 9


def test_snapshot_failure_of_one_venue_does_not_repeat_the_other(make_env) -> None:  # type: ignore[no-untyped-def]
    k = FakeSource("kalshi", [mk("A")])
    p = FakeSource(
        "polymarket", [mk("0xP", venue="polymarket", series_ticker=None, token_ids={"yes": "TY"})]
    )
    env = make_env(k, p)
    env.allow_catalog()
    env.svc.run_due()
    k.fail_lookup = True
    base = len(p.lookup_calls)
    base_k = len(k.lookup_calls)
    for _ in range(4):
        env.clock.advance(timedelta(minutes=1))
        env.svc.run_due()
    assert len(p.lookup_calls) == base  # 4 minutes < 5-minute cadence: Polymarket not re-polled
    assert len(k.lookup_calls) == base_k  # and the failing venue is not hammered each minute


def test_run_due_never_raises_so_the_scheduler_keeps_ticking(make_env) -> None:  # type: ignore[no-untyped-def]
    class Boom(FakeSource):
        def fetch_markets(self, ids: list[str]):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    env = make_env(Boom("kalshi", [mk("A")]))
    env.svc.run_due()  # must not raise
    env.clock.advance(timedelta(minutes=10))
    env.svc.run_due()


# -- checker 3: non-Yes/No outcomes ---------------------------------------------------------
def test_non_binary_market_records_what_yes_means_and_has_a_yes_token(make_client) -> None:  # type: ignore[no-untyped-def]
    ev = next(
        e
        for e in body_of("poly_events_page1.json")["events"]
        if e["title"].startswith("Will Anthropic or OpenAI IPO first")
    )
    raw = ev["markets"][0]
    src = poly(make_client, lambda r: json_response({}))
    m = src.parse_market(ev, raw)
    assert m is not None
    assert m.yes_label == "Anthropic"  # the first outcome; bid/ask/last refer to it
    assert m.token_ids["yes"] == m.token_ids["anthropic"]  # alias so history backfill works
    assert "openai" in m.token_ids
    binary = src.parse_market(poly_event(), poly_event()["markets"][0])
    assert binary is not None and binary.yes_label == "Yes"


def test_yes_label_is_stored(make_env) -> None:  # type: ignore[no-untyped-def]
    src = FakeSource(
        "polymarket",
        [
            mk(
                "0xP",
                venue="polymarket",
                series_ticker=None,
                yes_label="Anthropic",
                token_ids={"yes": "T"},
            )
        ],
    )
    env = make_env(src)
    env.svc.catalog_pass("polymarket")
    assert env.one("select yes_label from markets")[0] == "Anthropic"


# -- minor: config validation and log noise --------------------------------------------------
def test_settings_reject_nonsense_values() -> None:
    with pytest.raises(ValidationError):
        Settings(min_vol24_usd=-1, _env_file=None)
    with pytest.raises(ValidationError):
        Settings(snapshot_fast_minutes=60, snapshot_slow_minutes=5, _env_file=None)
    Settings(snapshot_fast_minutes=5, snapshot_slow_minutes=5, _env_file=None)


def test_httpx_request_logging_is_quiet() -> None:
    configure_logging()
    assert logging.getLogger("httpx").level >= logging.WARNING
