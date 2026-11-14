from __future__ import annotations

from datetime import UTC, datetime

import httpx
from ingest_helpers import body_of, json_response

from prooflag.ingest.kalshi import KalshiSource

BASE = "https://kalshi.test/trade-api/v2"


def test_historical_markets_use_series_filter_and_cursor(make_client, requests_log) -> None:  # type: ignore[no-untyped-def]
    page = body_of("kalshi_historical_markets.json")

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/historical/markets")
        if dict(req.url.params).get("cursor") == "NEXT":
            return json_response({"markets": [], "cursor": ""})
        return json_response({**page, "cursor": "NEXT"})

    src = KalshiSource(make_client(handler), BASE)
    got = list(src.iter_historical_markets("KXEOWEEK"))
    assert [m["ticker"] for m in got] == [m["ticker"] for m in page["markets"]]
    q = dict(requests_log[0].url.params)
    assert q["series_ticker"] == "KXEOWEEK" and q["limit"] == "1000"
    assert len(requests_log) == 2


def test_trades_are_parsed_with_exact_times_prices_and_sizes(make_client, requests_log) -> None:  # type: ignore[no-untyped-def]
    page = body_of("kalshi_trades_page.json")

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/markets/trades")
        if dict(req.url.params).get("cursor"):
            return json_response({"trades": [], "cursor": ""})
        return json_response(page)

    src = KalshiSource(make_client(handler), BASE)
    t0 = datetime(2026, 10, 18, tzinfo=UTC)
    trades = list(src.iter_trades("KXEOWEEK-26OCT24-1", min_ts=t0))
    assert len(trades) == len(page["trades"])
    first = trades[0]
    raw = page["trades"][0]
    assert first.price == float(raw["yes_price_dollars"]) and first.count == float(raw["count_fp"])
    assert first.ts == datetime.fromisoformat(raw["created_time"].replace("Z", "+00:00"))
    assert first.ts.tzinfo is not None and first.trade_id == raw["trade_id"]
    assert first.taker_side == raw["taker_side"]
    q = dict(requests_log[0].url.params)
    assert q["ticker"] == "KXEOWEEK-26OCT24-1" and q["limit"] == "1000"
    assert q["min_ts"] == str(int(t0.timestamp()))


def test_all_trades_merges_live_and_historical_sorted_and_deduped(make_client) -> None:  # type: ignore[no-untyped-def]
    live = body_of("kalshi_trades_page.json")
    hist = body_of("kalshi_historical_trades_page.json")
    overlap = hist["trades"][0]
    live_with_overlap = {"trades": [*live["trades"], overlap], "cursor": ""}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/historical/trades"):
            return json_response({**hist, "cursor": ""})
        return json_response(live_with_overlap)

    src = KalshiSource(make_client(handler), BASE)
    trades = src.all_trades("KXEOWEEK-26SEP12-1")
    ids = [t.trade_id for t in trades]
    assert len(ids) == len(set(ids))  # the overlapping trade is counted once
    assert len(trades) == len(live["trades"]) + len(hist["trades"])
    assert [t.ts for t in trades] == sorted(t.ts for t in trades)


def test_malformed_trade_is_skipped_and_counted(make_client) -> None:  # type: ignore[no-untyped-def]
    page = body_of("kalshi_trades_page.json")
    bad = {**page["trades"][0], "yes_price_dollars": "not-a-price", "trade_id": "bad1"}
    page = {"trades": [bad, *page["trades"][:2]], "cursor": ""}
    src = KalshiSource(make_client(lambda r: json_response(page)), BASE)
    assert len(list(src.iter_trades("T"))) == 2
    assert src.parse_errors == 1
