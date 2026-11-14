"""E1 data fetch: pull every input of the edge study from the free public APIs and store it under
studies/e1/inputs/ (tracked, gzip, deterministic) so docs/edge-study.md can be regenerated offline.

Kalshi/Polymarket/Federal Register requests use the generic venue User-Agent; only the SEC call
uses the configured contact (settings.user_agent). Rate limits: Kalshi 4/s, FR 1/s.

Usage: python scripts/edge_fetch.py [--skip-kalshi] [--skip-fr] [--skip-misc]
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import sqlite3
import subprocess
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from prooflag.config import Settings
from prooflag.ingest.http import VenueClient, VenueHTTPError
from prooflag.ingest.kalshi import KalshiSource
from prooflag.ingest.polymarket import PolymarketSource
from prooflag.logging import configure_logging
from prooflag.redact import default_redactor

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "studies" / "e1" / "inputs"
SERIES = "KXEOWEEK"
FR = "https://www.federalregister.gov/api/v1"
log = logging.getLogger("edge_fetch")


def save(name: str, obj: Any) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    with (
        (OUT / f"{name}.json.gz").open("wb") as fh,
        gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as z,
    ):
        z.write(raw)
    print(f"saved {name}.json.gz ({len(raw) / 1e6:.2f} MB raw)", flush=True)


def fetch_kalshi(settings: Settings) -> None:
    client = VenueClient(user_agent=settings.venue_user_agent, max_rps=settings.venue_max_rps)
    src = KalshiSource(client, settings.kalshi_base)
    keep = (
        "ticker",
        "event_ticker",
        "result",
        "status",
        "open_time",
        "close_time",
        "settlement_ts",
        "rules_primary",
        "title",
        "yes_sub_title",
        "strike_type",
        "floor_strike",
    )
    markets: dict[str, dict[str, Any]] = {}
    for status in ("open", "closed", "settled"):
        for ev in src.iter_events(status=status, series_ticker=SERIES):
            for m in ev.get("markets") or []:
                markets[m["ticker"]] = {k: m.get(k) for k in keep}
    for m in src.iter_historical_markets(SERIES):
        markets.setdefault(m["ticker"], {k: m.get(k) for k in keep})
    # only markets with a recorded result can be evaluated; keep open ones in the manifest only
    resolved = {t: m for t, m in markets.items() if m.get("result") in ("yes", "no")}
    print(f"kalshi markets: {len(markets)} total, {len(resolved)} resolved", flush=True)
    save("kalshi_markets", sorted(resolved.values(), key=lambda m: m["ticker"]))

    trades: dict[str, list[list[Any]]] = {}
    candles: dict[str, list[list[Any]]] = {}
    for i, (ticker, m) in enumerate(sorted(resolved.items()), 1):
        if "-" not in ticker or not m.get("open_time") or not m.get("close_time"):
            continue
        t0 = datetime.fromisoformat(m["open_time"].replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
        series_ticker = ticker.split("-")[0]
        trades[ticker] = [
            [t.ts.isoformat(), t.price, t.count, t.taker_side, t.trade_id]
            for t in src.all_trades(ticker)
        ]
        try:
            pts = src.price_history(series_ticker, ticker, t0, t1 + timedelta(hours=1), 60)
        except VenueHTTPError as e:
            print("candles failed", ticker, e.status)
            pts = []
        candles[ticker] = [[p.ts.isoformat(), p.yes_bid, p.yes_ask, p.price] for p in pts]
        if i % 20 == 0:
            print(f"  {i}/{len(resolved)} markets", flush=True)
    save("kalshi_trades", trades)
    save("kalshi_candles", candles)
    fees = client.get_json(f"{settings.kalshi_base}/series/{SERIES}")
    s = fees.get("series", fees)
    save(
        "kalshi_fee_info",
        {k: s.get(k) for k in ("fee_type", "fee_multiplier", "frequency", "title")},
    )


def fetch_fr(settings: Settings) -> None:
    client = VenueClient(user_agent=settings.venue_user_agent, max_rps=1.0)
    docs: list[dict[str, Any]] = []
    page = 1
    while True:
        d = client.get_json(
            f"{FR}/documents.json",
            {
                "conditions[presidential_document_type][]": "executive_order",
                "conditions[signing_date][gte]": "2025-08-01",
                "per_page": 100,
                "page": page,
                "order": "oldest",
                "fields[]": [
                    "document_number",
                    "executive_order_number",
                    "signing_date",
                    "publication_date",
                    "title",
                    "public_inspection_pdf_url",
                ],
            },
        )
        docs += d["results"]
        if not d.get("next_page_url"):
            break
        page += 1
    print(f"FR executive orders: {len(docs)}", flush=True)
    out = []
    for i, e in enumerate(docs, 1):
        pi: dict[str, Any] | None = None
        try:
            r = client.get_json(f"{FR}/public-inspection-documents/{e['document_number']}.json")
            pi = {
                "filed_at": r.get("filed_at"),
                "filing_type": r.get("filing_type"),
                "publication_date": r.get("publication_date"),
            }
        except VenueHTTPError as err:
            pi = {"error": err.status}
        url = e.get("public_inspection_pdf_url") or ""
        url_ts = url.split("?")[-1] if "?" in url else None
        out.append({**e, "pi": pi, "pi_url_ts": url_ts})
        if i % 20 == 0:
            print(f"  {i}/{len(docs)} EOs", flush=True)
    save("fr_eos", out)


def fetch_misc(settings: Settings) -> None:
    client = VenueClient(user_agent=settings.venue_user_agent, max_rps=2.0)
    # Strategy case: finest available CLOB history around the 8-K.
    fx = json.loads(
        (ROOT / "fixtures/strategy_2026_05/polymarket_market_may31.json").read_text(
            encoding="utf-8"
        )
    )
    token = json.loads(fx["clobTokenIds"])[0]
    start = int(datetime(2026, 5, 31, 12, tzinfo=UTC).timestamp())
    end = int(datetime(2026, 6, 2, 12, tzinfo=UTC).timestamp())
    res: dict[str, Any] = {}
    for fid in (1, 5, 10):
        try:
            h = client.get_json(
                "https://clob.polymarket.com/prices-history",
                {"market": token, "startTs": start, "endTs": end, "fidelity": fid},
            )
            res[str(fid)] = h.get("history", [])
            print(f"strategy CLOB fidelity {fid}: {len(res[str(fid)])} points", flush=True)
            if res[str(fid)]:
                break
        except VenueHTTPError as e:
            print("fidelity", fid, "->", e.status)
    save(
        "strategy_prices",
        {
            "token": token,
            "history": res,
            "fee_schedule": fx.get("feeSchedule"),
            "fees_enabled": fx.get("feesEnabled"),
        },
    )
    # Allow-list status of every curated market (from the local DB).
    db = settings.db_path
    if db.exists():
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "select m.venue, m.market_id, m.title, m.status, m.result, m.cluster_id, m.close_time_utc,"
            " (select a.reason from watch_allowlist a where a.venue=m.venue and a.key=m.market_id"
            "  order by a.entry_id desc limit 1) as reason"
            " from markets m where m.watched=1"
        ).fetchall()
        save("allowlist_status", [dict(r) for r in rows])
    # EDGAR: have Anthropic / OpenAI filed a (public) S-1? SEC contact UA from settings.
    found: dict[str, Any] = {}
    for name in ("anthropic", "openai"):
        url = (
            f"https://www.sec.gov/cgi-bin/browse-edgar?company={name}&type=S-1&owner=include"
            "&count=40&action=getcompany&output=atom"
        )
        req = urllib.request.Request(url, headers={"User-Agent": settings.user_agent})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read().decode("utf-8", "replace")
            found[name] = {"entries": body.count("<entry>"), "snippet": body[:300]}
        except Exception as e:
            found[name] = {"error": str(e)}
        time.sleep(1)
    save("edgar_ipo_check", found)


ANTHROPIC_CIK = 2130357  # Anthropic, PBC (verified from EDGAR submissions: name, ticker ANT)


def fetch_ipo(settings: Settings) -> None:
    """Anthropic IPO cluster: EDGAR filing times + Kalshi trades + Polymarket CLOB prices."""
    req = urllib.request.Request(
        f"https://data.sec.gov/submissions/CIK{ANTHROPIC_CIK:010d}.json",
        headers={"User-Agent": settings.user_agent},  # SEC only: the configured contact
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        sub = json.load(r)
    rec = sub["filings"]["recent"]
    filings = [
        {
            "form": rec["form"][i],
            "accepted_utc": rec["acceptanceDateTime"][i],
            "accession": rec["accessionNumber"][i],
            "filing_date": rec["filingDate"][i],
        }
        for i in range(len(rec["form"]))
        if rec["filingDate"][i] >= "2026-06-01"
    ]
    print(
        f"EDGAR {sub['name']} ({sub.get('tickers')}): {len(filings)} filings since 2026-06-01",
        flush=True,
    )
    client = VenueClient(user_agent=settings.venue_user_agent, max_rps=settings.venue_max_rps)
    kal = KalshiSource(client, settings.kalshi_base)
    pm = PolymarketSource(client, settings.gamma_base, settings.clob_base)
    since = datetime(2026, 10, 15, tzinfo=UTC)
    kalshi: dict[str, Any] = {}
    seen: set[str] = set()
    for status in ("open", "closed", "settled"):
        for ev in kal.iter_events(status=status, series_ticker="KXIPOANTHROPIC"):
            for m in ev.get("markets") or []:
                if m["ticker"] in seen:
                    continue
                seen.add(m["ticker"])
                tr = [t for t in kal.all_trades(m["ticker"]) if t.ts >= since]
                kalshi[m["ticker"]] = {
                    "title": m.get("title"),
                    "status": m.get("status"),
                    "result": m.get("result"),
                    "trades": [
                        [t.ts.isoformat(), t.price, t.count, t.taker_side, t.trade_id] for t in tr
                    ],
                }
    print(f"Kalshi KXIPOANTHROPIC markets: {len(kalshi)}", flush=True)
    poly: dict[str, Any] = {}
    db = settings.db_path
    if db.exists():
        c = sqlite3.connect(db)
        rows = c.execute(
            "select m.market_id, m.title, t.token_id from markets m join market_tokens t"
            " on t.venue=m.venue and t.market_id=m.market_id and t.outcome='yes'"
            " where m.venue='polymarket' and m.cluster_id='issuer_ipo_family'"
            " and m.title like '%Anthropic%' and m.title like '%IPO%' and m.status in ('open','past_end')"
            " and m.yes_label='Yes' order by m.vol24_usd_est desc limit 8"
        ).fetchall()
        for mid, title, token in rows:
            pts = pm.price_history(token, since, datetime(2026, 11, 14, 12, tzinfo=UTC), 10)
            poly[mid] = {"title": title, "points": [[p.ts.isoformat(), p.price] for p in pts]}
        print(f"Polymarket IPO markets: {len(poly)}", flush=True)
    save(
        "ipo_cluster",
        {
            "cik": ANTHROPIC_CIK,
            "name": sub["name"],
            "tickers": sub.get("tickers"),
            "filings": filings,
            "kalshi": kalshi,
            "polymarket": poly,
        },
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-kalshi", action="store_true")
    ap.add_argument("--skip-fr", action="store_true")
    ap.add_argument("--skip-misc", action="store_true")
    ap.add_argument("--skip-ipo", action="store_true")
    ap.add_argument("--only-ipo", action="store_true")
    args = ap.parse_args()
    configure_logging(redactor=default_redactor())
    settings = Settings()
    settings.require_real_contact()  # SEC calls below need a real contact
    if args.only_ipo:
        fetch_ipo(settings)
        return
    if not args.skip_kalshi:
        fetch_kalshi(settings)
    if not args.skip_fr:
        fetch_fr(settings)
    if not args.skip_misc:
        fetch_misc(settings)
    if not args.skip_ipo:
        fetch_ipo(settings)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    save(
        "manifest",
        {
            "fetched_at": datetime.now(UTC).isoformat(),
            "code_git_sha": sha,
            "series": SERIES,
            "note": "inputs for docs/edge-study.md; see scripts/edge_fetch.py",
        },
    )


if __name__ == "__main__":
    main()
