from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from ingest_helpers import body_of, fixture, json_response

from prooflag.ingest.http import VenueHTTPError
from prooflag.ingest.kalshi import KalshiSource

BASE = "https://kalshi.test/trade-api/v2"


def page_handler(req: httpx.Request) -> httpx.Response:
    q = dict(req.url.params)
    if req.url.path.endswith("/events"):
        if q.get("cursor") == "CURSOR_PAGE2":
            return json_response(body_of("kalshi_events_last_page_empty.json"))
        return json_response(body_of("kalshi_events_page1.json"))
    raise AssertionError(f"unexpected request {req.url}")


def test_iter_markets_excludes_sports_and_paginates_to_empty_last_page(
    make_client, requests_log
) -> None:  # type: ignore[no-untyped-def]
    src = KalshiSource(make_client(page_handler), BASE)
    markets = list(src.iter_markets(status="open"))
    assert markets
    assert all(m.category != "Sports" for m in markets)
    page1 = body_of("kalshi_events_page1.json")["events"]
    sports_tickers = {
        m["ticker"] for ev in page1 if ev["category"] == "Sports" for m in ev["markets"]
    }
    assert sports_tickers  # fixture really contains a sports event
    assert not sports_tickers & {m.market_id for m in markets}
    assert len(requests_log) == 2
    q1, q2 = dict(requests_log[0].url.params), dict(requests_log[1].url.params)
    assert q1["status"] == "open" and q1["with_nested_markets"] == "true" and q1["limit"] == "200"
    assert "cursor" not in q1 and q2["cursor"] == "CURSOR_PAGE2"


def test_market_fields_units_and_dollar_estimate(make_client) -> None:  # type: ignore[no-untyped-def]
    src = KalshiSource(make_client(page_handler), BASE)
    by_id = {m.market_id: m for m in src.iter_markets(status="open")}
    eo = next(m for m in by_id.values() if m.series_ticker == "KXEOWEEK")
    raw = next(
        mk
        for ev in body_of("kalshi_events_page1.json")["events"]
        for mk in ev["markets"]
        if mk["ticker"] == eo.market_id
    )
    assert eo.vol24_contracts == pytest.approx(float(raw["volume_24h_fp"]))
    assert eo.open_interest_contracts == pytest.approx(float(raw["open_interest_fp"]))
    assert eo.liquidity_usd is None  # Kalshi has no liquidity field; never faked
    last = float(raw["last_price_dollars"])
    assert eo.last_price == pytest.approx(last)
    assert eo.vol24_usd_est == pytest.approx(float(raw["volume_24h_fp"]) * last)
    assert eo.rules_primary == raw["rules_primary"]
    assert eo.series_ticker == "KXEOWEEK" and eo.event_id and eo.event_title
    assert eo.close_time is not None and eo.close_time.tzinfo is not None


def test_dollar_estimate_falls_back_to_mid_then_none(make_client) -> None:  # type: ignore[no-untyped-def]
    src = KalshiSource(make_client(page_handler), BASE)
    ev = {"event_ticker": "E", "series_ticker": "S", "title": "t", "category": "Politics"}
    base = {
        "ticker": "E-1",
        "title": "m",
        "rules_primary": "r",
        "status": "active",
        "volume_24h_fp": "1000.00",
        "open_interest_fp": "0.00",
    }
    no_last = src.parse_market(
        ev, {**base, "last_price_dollars": "", "yes_bid_dollars": "0.10", "yes_ask_dollars": "0.20"}
    )
    assert no_last is not None and no_last.vol24_usd_est == pytest.approx(150.0)
    nothing = src.parse_market(ev, {**base})
    assert nothing is not None and nothing.vol24_usd_est is None


def test_multivariate_markets_are_dropped(make_client) -> None:  # type: ignore[no-untyped-def]
    src = KalshiSource(make_client(page_handler), BASE)
    mve = body_of("kalshi_markets_mve_only.json")["markets"]
    assert mve
    ev = {
        "event_ticker": mve[0]["event_ticker"],
        "series_ticker": "KXMVECROSSCATEGORY",
        "title": "combo",
        "category": "Mentions",
    }
    assert all(src.parse_market(ev, m) is None for m in mve)


def test_settled_events_map_status_and_result(make_client, requests_log) -> None:  # type: ignore[no-untyped-def]
    def handler(req: httpx.Request) -> httpx.Response:
        return json_response(body_of("kalshi_events_eo_settled.json"))

    src = KalshiSource(make_client(handler), BASE)
    ms = list(src.iter_markets(status="settled", series_ticker="KXEOWEEK"))
    assert ms and all(m.status == "settled" for m in ms)
    assert {m.result for m in ms} <= {"yes", "no"}
    assert all(m.series_ticker == "KXEOWEEK" for m in ms)
    q = dict(requests_log[0].url.params)
    assert q["series_ticker"] == "KXEOWEEK" and q["status"] == "settled"


def test_fetch_markets_batches_100_tickers(make_client, requests_log) -> None:  # type: ignore[no-untyped-def]
    def handler(req: httpx.Request) -> httpx.Response:
        return json_response(body_of("kalshi_markets_by_tickers.json"))

    src = KalshiSource(make_client(handler), BASE)
    got = src.fetch_markets([f"T-{i}" for i in range(250)])
    assert len(requests_log) == 3
    sizes = [len(dict(r.url.params)["tickers"].split(",")) for r in requests_log]
    assert sizes == [100, 100, 50]
    assert got and all(m.market_id for m in got)


def test_price_history_keeps_null_trade_prices_and_bid_ask(make_client) -> None:  # type: ignore[no-untyped-def]
    def handler(req: httpx.Request) -> httpx.Response:
        return json_response(body_of("kalshi_candlesticks.json"))

    src = KalshiSource(make_client(handler), BASE)
    end = datetime(2026, 11, 14, tzinfo=UTC)
    pts = src.price_history("KXEOWEEK", "KXEOWEEK-26NOV14-0", end - timedelta(days=3), end, 60)
    assert len(pts) == len(body_of("kalshi_candlesticks.json")["candlesticks"])
    assert any(p.price is None for p in pts)  # no trade in that candle: not invented
    assert any(p.price is not None for p in pts)
    assert all(p.yes_bid is not None or p.yes_ask is not None for p in pts)
    assert [p.ts for p in pts] == sorted(p.ts for p in pts)
    assert all(p.ts.tzinfo is not None for p in pts)


def test_price_history_chunks_to_stay_under_5000_candles(make_client, requests_log) -> None:  # type: ignore[no-untyped-def]
    def handler(req: httpx.Request) -> httpx.Response:
        return json_response({"candlesticks": [], "ticker": "X"})

    src = KalshiSource(make_client(handler), BASE)
    start = datetime(2026, 11, 1, tzinfo=UTC)
    src.price_history("S", "S-1", start, start + timedelta(days=10), 1)  # 14400 one-minute candles
    spans = [
        (int(dict(r.url.params)["start_ts"]), int(dict(r.url.params)["end_ts"]))
        for r in requests_log
    ]
    assert len(spans) == 3
    assert all((e - s) / 60 <= 5000 for s, e in spans)
    assert spans[0][0] == int(start.timestamp())
    assert spans[-1][1] == int((start + timedelta(days=10)).timestamp())
    assert all(a[1] == b[0] for a, b in itertools.pairwise(spans))


def test_candlestick_400_too_many_is_an_error(make_client) -> None:  # type: ignore[no-untyped-def]
    rec = fixture("kalshi_candlesticks_too_many_400.json")

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(rec["status"], json=rec["body"])

    src = KalshiSource(make_client(handler), BASE)
    start = datetime(2026, 11, 1, tzinfo=UTC)
    with pytest.raises(VenueHTTPError) as ei:
        src.price_history("S", "S-1", start, start + timedelta(days=1), 1)
    assert ei.value.status == 400
