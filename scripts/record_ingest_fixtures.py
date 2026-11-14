"""Record REAL venue responses as test fixtures (tests/fixtures/ingest/). Run manually; tests
never touch the network. Pages are assembled from real event/market objects (unmodified) with
synthetic cursors; single responses (422, empty page, lookups, history) are recorded verbatim.

Usage: python scripts/record_ingest_fixtures.py
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "ingest"
UA = "Prooflag/0.1 (fixture recorder)"
K = "https://external-api.kalshi.com/trade-api/v2"
G = "https://gamma-api.polymarket.com"
C = "https://clob.polymarket.com"


def raw(url: str, params: dict | None = None) -> tuple[int, str]:
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    time.sleep(0.4)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def save(name: str, obj: object) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    print("saved", name)


def save_raw(name: str, status: int, body: str) -> None:
    try:
        parsed: object = json.loads(body)
    except json.JSONDecodeError:
        parsed = body
    save(name, {"status": status, "body": parsed})


def pick_kalshi() -> None:
    picks: dict[str, dict] = {}
    cursor = ""
    for _ in range(60):
        params: dict = {"status": "open", "limit": 200, "with_nested_markets": "true"}
        if cursor:
            params["cursor"] = cursor
        _, body = raw(K + "/events", params)
        d = json.loads(body)
        for ev in d["events"]:
            st = ev.get("series_ticker") or ""
            if ev.get("category") == "Sports" and "sports" not in picks:
                picks["sports"] = ev
            elif st.startswith("KXMVE") and "mve" not in picks:
                picks["mve"] = ev
            elif st == "KXEOWEEK" and "eo_open" not in picks:
                picks["eo_open"] = ev
            elif (
                "Anthropic's IPO" in ev["title"]
                and "ipo_bank" not in picks
                and "lead" in ev["title"]
            ):
                picks["ipo_bank"] = ev
            elif (
                ev.get("category") == "Companies" and "company" not in picks and "sec" not in picks
            ):
                picks["company"] = ev
            elif (
                "fed" in ev["title"].lower() and "Fed funds" in ev["title"] and "fomc" not in picks
            ):
                picks["fomc"] = ev
        cursor = d.get("cursor") or ""
        if not cursor or len(picks) >= 6:
            break
    # Weekly EO series is fetched by series_ticker (it can sit deep in the paged listing).
    s, body = raw(
        K + "/events",
        {
            "series_ticker": "KXEOWEEK",
            "status": "open",
            "with_nested_markets": "true",
            "limit": 200,
        },
    )
    picks["eo_open"] = json.loads(body)["events"][-1]
    # Multivariate (combo) markets are not in /events; record the real /markets?mve_filter=only shape.
    s, body = raw(K + "/markets", {"mve_filter": "only", "limit": 2, "status": "open"})
    save_raw("kalshi_markets_mve_only.json", s, body)
    print("kalshi picks", sorted(picks))
    save("kalshi_events_page1.json", {"events": list(picks.values()), "cursor": "CURSOR_PAGE2"})
    # Real empty last page (series with no closed events).
    s, body = raw(
        K + "/events",
        {
            "series_ticker": "KXEOWEEK",
            "status": "closed",
            "with_nested_markets": "true",
            "limit": 200,
        },
    )
    save_raw("kalshi_events_last_page_empty.json", s, body)
    # Settled EO weeks (primary eval source).
    s, body = raw(
        K + "/events",
        {
            "series_ticker": "KXEOWEEK",
            "status": "settled",
            "with_nested_markets": "true",
            "limit": 3,
        },
    )
    d = json.loads(body)
    save("kalshi_events_eo_settled.json", {"events": d["events"][:3], "cursor": ""})
    eo = picks["eo_open"]["markets"][0]
    tickers = [m["ticker"] for ev in list(picks.values())[:3] for m in ev["markets"][:2]]
    s, body = raw(K + "/markets", {"tickers": ",".join(tickers)})
    save_raw("kalshi_markets_by_tickers.json", s, body)
    now = int(time.time())
    s, body = raw(
        K + f"/series/KXEOWEEK/markets/{eo['ticker']}/candlesticks",
        {"start_ts": now - 3 * 86400, "end_ts": now, "period_interval": 60},
    )
    save_raw("kalshi_candlesticks.json", s, body)
    s, body = raw(
        K + f"/series/KXEOWEEK/markets/{eo['ticker']}/candlesticks",
        {"start_ts": now - 30 * 86400, "end_ts": now, "period_interval": 1},
    )
    save_raw("kalshi_candlesticks_too_many_400.json", s, body)


def pick_poly() -> None:
    picks: dict[str, dict] = {}
    cursor = ""
    for _ in range(120):
        params: dict = {"closed": "false", "active": "true", "archived": "false", "limit": 50}
        if cursor:
            params["after_cursor"] = cursor
        _, body = raw(G + "/events/keyset", params)
        d = json.loads(body)
        for ev in d["events"]:
            labels = [(t.get("label") or "").lower() for t in ev.get("tags") or []]
            title = ev.get("title", "")
            mk = ev.get("markets") or []
            if "sports" in labels and "sports" not in picks:
                picks["sports"] = ev
            elif any(m.get("comboStatus") == "enabled" for m in mk) and "combo" not in picks:
                picks["combo"] = ev
            elif "IPO" in title and "Anthropic" in title and "ipo" not in picks:
                picks["ipo"] = ev
            elif "Fed Decision" in title and "fomc" not in picks:
                picks["fomc"] = ev
            elif "ipo" not in picks and "Anthropic" in title:
                continue
            elif (
                any(
                    m.get("endDate", "9") < time.strftime("%Y-%m-%d") and not m.get("closed")
                    for m in mk
                )
                and "past_end" not in picks
            ):
                picks["past_end"] = ev
            elif "plain" not in picks and "sports" not in labels and mk:
                picks["plain"] = ev
        cursor = d.get("next_cursor") or ""
        if not cursor or len(picks) >= 6:
            break
    print("poly picks", sorted(picks))
    save("poly_events_page1.json", {"events": list(picks.values()), "next_cursor": "CURSOR_PAGE2"})
    s, body = raw(
        G + "/events/keyset", {"closed": "false", "slug": "no-such-event-zzz", "limit": 50}
    )
    save_raw("poly_events_last_page_empty.json", s, body)
    s, body = raw(G + "/markets/keyset", {"limit": 2, "offset": 10})
    save_raw("poly_offset_422.json", s, body)
    s, body = raw(G + "/events/keyset", {"closed": "false", "limit": 100})
    save_raw("poly_events_limit100_406.json", s, body)
    conds = [m["conditionId"] for ev in picks.values() for m in (ev.get("markets") or [])[:1]][:5]
    s, body = raw(G + "/markets", {"condition_ids": conds, "limit": 50})
    save_raw("poly_markets_by_condition.json", s, body)
    strat = json.loads(
        (
            Path(__file__).resolve().parent.parent
            / "fixtures/strategy_2026_05/polymarket_market_may31.json"
        ).read_text(encoding="utf-8")
    )
    s, body = raw(G + "/markets", {"condition_ids": strat["conditionId"], "closed": "true"})
    save_raw("poly_markets_closed_by_condition.json", s, body)
    s, body = raw(G + "/markets", {"condition_ids": strat["conditionId"]})
    save_raw("poly_markets_closed_missing_without_flag.json", s, body)
    tok = json.loads(strat["clobTokenIds"])[0]
    end = 1780704000
    s, body = raw(
        C + "/prices-history",
        {"market": tok, "startTs": end - 7 * 86400, "endTs": end, "fidelity": 720},
    )
    save_raw("clob_prices_history.json", s, body)
    s, body = raw(
        C + "/prices-history",
        {"market": tok, "startTs": end - 30 * 86400, "endTs": end, "fidelity": 60},
    )
    save_raw("clob_prices_history_too_long_400.json", s, body)


if __name__ == "__main__":
    pick_kalshi()
    pick_poly()
