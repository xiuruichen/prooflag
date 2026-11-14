from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from ingest_helpers import body_of, fixture, json_response

from prooflag.ingest.http import VenueHTTPError
from prooflag.ingest.polymarket import PolymarketSource

GAMMA = "https://gamma.test"
CLOB = "https://clob.test"
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def source(make_client, handler) -> PolymarketSource:  # type: ignore[no-untyped-def]
    return PolymarketSource(make_client(handler), GAMMA, CLOB, clock=lambda: NOW)


def events_handler(req: httpx.Request) -> httpx.Response:
    q = dict(req.url.params)
    assert req.url.path.endswith("/events/keyset")
    if q.get("after_cursor") == "CURSOR_PAGE2":
        return json_response(body_of("poly_events_last_page_empty.json"))
    return json_response(body_of("poly_events_page1.json"))


def test_catalog_uses_keyset_cursor_never_offset_and_ends_on_empty_page(
    make_client, requests_log
) -> None:  # type: ignore[no-untyped-def]
    list(source(make_client, events_handler).iter_markets())
    assert len(requests_log) == 2
    q1, q2 = (dict(r.url.params) for r in requests_log)
    assert q1["closed"] == "false" and q1["active"] == "true" and q1["archived"] == "false"
    assert q1["limit"] == "50"  # >50 is served gzip-only (406 otherwise)
    assert "after_cursor" not in q1 and q2["after_cursor"] == "CURSOR_PAGE2"
    assert all("offset" not in dict(r.url.params) for r in requests_log)


def _is_sports(ev: dict) -> bool:  # type: ignore[type-arg]
    return any((t.get("label") or "").lower() == "sports" for t in ev.get("tags", []))


def test_sports_events_and_combo_markets_are_excluded(make_client) -> None:  # type: ignore[no-untyped-def]
    src = source(make_client, events_handler)
    ids = {m.market_id for m in src.iter_markets()}
    page = body_of("poly_events_page1.json")["events"]
    sports_ids = {m["conditionId"] for ev in page if _is_sports(ev) for m in ev["markets"]}
    assert sports_ids and not sports_ids & ids
    # A combo market is excluded on comboStatus alone, even when the event is not tagged Sports.
    combo_ev = copy.deepcopy(
        next(e for e in page if any(m.get("comboStatus") == "enabled" for m in e["markets"]))
    )
    combo_ev["tags"] = [t for t in combo_ev["tags"] if (t.get("label") or "").lower() != "sports"]
    combos = [m for m in combo_ev["markets"] if m.get("comboStatus") == "enabled"]
    assert combos and all(src.parse_market(combo_ev, m) is None for m in combos)


def test_json_string_fields_are_parsed_and_units_are_usd(make_client) -> None:  # type: ignore[no-untyped-def]
    src = source(make_client, events_handler)
    by_id = {m.market_id: m for m in src.iter_markets()}
    ev = next(
        e
        for e in body_of("poly_events_page1.json")["events"]
        if e["title"].startswith("Fed Decision")
    )
    raw = ev["markets"][0]
    m = by_id[raw["conditionId"]]
    assert isinstance(raw["outcomePrices"], str) and isinstance(raw["clobTokenIds"], str)
    assert set(m.token_ids) == {"yes", "no"}
    assert m.token_ids["yes"] and m.token_ids["yes"] != m.token_ids["no"]
    assert m.vol24_usd_est == pytest.approx(float(raw["volume24hr"]))
    assert m.vol24_contracts is None and m.open_interest_contracts is None
    assert m.liquidity_usd == pytest.approx(float(raw["liquidityNum"]))  # separate, never OI
    assert m.yes_bid == pytest.approx(float(raw["bestBid"])) and m.yes_ask == pytest.approx(
        float(raw["bestAsk"])
    )
    assert m.rules_primary == raw["description"]
    assert m.event_title == ev["title"] and "Fed" in m.venue_tags


def test_closed_market_is_settled_with_result_and_open_past_end_is_kept(make_client) -> None:  # type: ignore[no-untyped-def]
    page = body_of("poly_events_page1.json")["events"]
    src = source(make_client, events_handler)
    settled_ev, settled_mk = next(
        (e, m) for e in page for m in e["markets"] if m.get("closed") and m.get("conditionId")
    )
    sm = src.parse_market(settled_ev, settled_mk)
    assert sm is not None and sm.status == "settled"
    # Not closed but past endDate (awaiting resolution): kept, never dropped.
    plain = copy.deepcopy(
        next(e for e in page if e["title"].startswith("Will Anthropic or OpenAI"))
    )
    mk = plain["markets"][0]
    mk["endDate"] = (NOW - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    pm = src.parse_market(plain, mk)
    assert pm is not None and pm.status == "past_end" and pm.result is None


def test_strategy_market_result_no_from_outcome_prices(make_client) -> None:  # type: ignore[no-untyped-def]
    strat = body_of("poly_markets_closed_by_condition.json")[0]
    src = source(make_client, events_handler)
    m = src.parse_market(None, strat)
    assert m is not None and m.status == "settled" and m.result == "no"
    assert m.raw["umaResolutionStatuses"]


def test_fetch_markets_looks_up_closed_markets_with_second_call(make_client, requests_log) -> None:  # type: ignore[no-untyped-def]
    strat = body_of("poly_markets_closed_by_condition.json")[0]
    open_ones = body_of("poly_markets_by_condition.json")

    def handler(req: httpx.Request) -> httpx.Response:
        q = dict(req.url.params)
        if q.get("closed") == "true":
            return json_response([strat])
        return json_response(open_ones)  # closed markets are silently absent without closed=true

    src = source(make_client, handler)
    ids = [m["conditionId"] for m in open_ones] + [strat["conditionId"]]
    got = {m.market_id: m for m in src.fetch_markets(ids)}
    assert strat["conditionId"] in got and got[strat["conditionId"]].status == "settled"
    expected = {m["conditionId"] for m in open_ones if m.get("comboStatus") != "enabled"}
    assert expected and expected <= set(got)
    combos = {m["conditionId"] for m in open_ones if m.get("comboStatus") == "enabled"}
    assert combos and not combos & set(got)  # combo markets stay excluded on lookup too
    assert any(dict(r.url.params).get("closed") == "true" for r in requests_log)


def test_fetch_markets_batches_to_stay_under_url_limits(make_client, requests_log) -> None:  # type: ignore[no-untyped-def]
    src = source(make_client, lambda r: json_response([]))
    src.fetch_markets([f"0x{i:064x}" for i in range(95)])
    open_calls = [r for r in requests_log if dict(r.url.params).get("closed") != "true"]
    assert [len(r.url.params.get_list("condition_ids")) for r in open_calls] == [40, 40, 15]


def test_offset_422_is_surfaced_not_swallowed(make_client) -> None:  # type: ignore[no-untyped-def]
    rec = fixture("poly_offset_422.json")
    client = make_client(lambda r: httpx.Response(rec["status"], json=rec["body"]))
    with pytest.raises(VenueHTTPError) as ei:
        client.get_json(f"{GAMMA}/markets/keyset", {"limit": 2, "offset": 10})
    assert ei.value.status == 422


def test_price_history_chunks_into_14_day_windows_and_dedupes(make_client, requests_log) -> None:  # type: ignore[no-untyped-def]
    hist = body_of("clob_prices_history.json")

    def handler(req: httpx.Request) -> httpx.Response:
        return json_response(hist)

    src = source(make_client, handler)
    start = datetime(2026, 5, 1, tzinfo=UTC)
    pts = src.price_history("TOKEN", start, start + timedelta(days=30), fidelity_minutes=720)
    spans = [
        (int(dict(r.url.params)["startTs"]), int(dict(r.url.params)["endTs"])) for r in requests_log
    ]
    assert len(spans) == 3
    assert all(e - s <= 14 * 86400 for s, e in spans)
    assert all(
        dict(r.url.params)["fidelity"] == "720" and dict(r.url.params)["market"] == "TOKEN"
        for r in requests_log
    )
    assert len(pts) == len(hist["history"])  # identical points from each chunk are de-duplicated
    assert [p.ts for p in pts] == sorted(p.ts for p in pts)
    assert pts[0].price == pytest.approx(hist["history"][0]["p"])


def test_price_history_too_long_400_is_an_error(make_client) -> None:  # type: ignore[no-untyped-def]
    rec = fixture("clob_prices_history_too_long_400.json")
    client = make_client(lambda r: httpx.Response(rec["status"], json=rec["body"]))
    with pytest.raises(VenueHTTPError) as ei:
        client.get_json(f"{CLOB}/prices-history", {"market": "t", "startTs": 1, "endTs": 99999999})
    assert ei.value.status == 400
