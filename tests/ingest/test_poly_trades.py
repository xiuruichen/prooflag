from __future__ import annotations

import httpx
from ingest_helpers import body_of, json_response

from prooflag.ingest.polymarket import PolymarketSource


def test_v2_trades_become_yes_price_trades_without_wallets(make_client, requests_log) -> None:  # type: ignore[no-untyped-def]
    page = body_of("poly_v2_trades_page.json")

    def handler(req: httpx.Request) -> httpx.Response:
        if dict(req.url.params).get("cursor") == "NEXT":
            return json_response({"data": [], "pagination": {"has_more": False}})
        return json_response({**page, "pagination": {"has_more": True, "next_cursor": "NEXT"}})

    src = PolymarketSource(
        make_client(handler), "https://g.test", "https://c.test", data_base="https://d.test/v2"
    )
    cid = page["data"][0]["condition_id"]
    trades = list(src.iter_trades(cid))
    assert len(trades) == len(page["data"]) and len(requests_log) == 2
    q = dict(requests_log[0].url.params)
    assert q["conditionId"] == cid and q["limit"] == "1000"
    raw = page["data"][0]
    expect = raw["price"] if raw["outcome"] == "Yes" else 1 - raw["price"]
    assert trades[0].price == expect and trades[0].count == raw["size"]
    assert trades[0].ts.timestamp() == raw["timestamp"] and trades[0].ts.tzinfo is not None
    assert len({t.trade_id for t in trades}) == len(trades)
    assert not hasattr(trades[0], "proxy_wallet")


def test_no_outcome_trades_are_converted_to_the_yes_price(make_client) -> None:  # type: ignore[no-untyped-def]
    row = {
        "timestamp": 1_700_000_000,
        "price": 0.3,
        "size": 10.0,
        "side": "BUY",
        "outcome": "No",
        "outcome_index": 1,
        "transaction_hash": "0xabc",
    }
    src = PolymarketSource(
        make_client(lambda r: json_response({"data": [row], "pagination": {"has_more": False}})),
        "https://g.test",
        "https://c.test",
        data_base="https://d.test/v2",
    )
    [t] = list(src.iter_trades("0xcid"))
    assert abs(t.price - 0.7) < 1e-9


def test_malformed_trade_rows_are_skipped_and_counted(make_client) -> None:  # type: ignore[no-untyped-def]
    rows = [
        {"timestamp": "x", "price": 0.3, "size": 1, "outcome": "Yes", "outcome_index": 0},
        {
            "timestamp": 1_700_000_000,
            "price": 0.4,
            "size": 2,
            "outcome": "Yes",
            "outcome_index": 0,
            "transaction_hash": "0x1",
        },
    ]
    src = PolymarketSource(
        make_client(lambda r: json_response({"data": rows, "pagination": {"has_more": False}})),
        "https://g.test",
        "https://c.test",
        data_base="https://d.test/v2",
    )
    assert len(list(src.iter_trades("0xcid"))) == 1 and src.parse_errors == 1


def test_row_without_outcome_index_is_malformed_not_yes() -> None:
    import httpx

    from prooflag.ingest.http import VenueClient
    from prooflag.ingest.polymarket import PolymarketSource

    page = {"data": [{"timestamp": 1, "price": 0.3, "size": 1}], "pagination": {"has_more": False}}
    vc = VenueClient(
        user_agent="t",
        max_rps=100,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=page)),
    )
    src = PolymarketSource(vc, "http://g", "http://c", data_base="http://d")
    assert list(src.iter_trades("0xabc")) == []
    assert src.parse_errors == 1
