"""F2 (v2): standalone slice count over OPEN, non-sports, non-combo markets.

Kalshi:     GET /events?status=open&with_nested_markets=true (non-multivariate; skip category Sports)
Polymarket: GET /events/keyset?closed=false&active=true (skip tag Sports; skip combo markets)
Stdlib only, read-only, no keys. Writes data/slice_candidates.json (all regex-tagged markets,
with event category/tags/settlement sources) and a summary report. Reports whether the scan
completed (cursor exhausted) per venue.

Usage: python scripts/slice_count.py [--max-pages N] [--out slice_report.md]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

UA = "Prooflag-slice-count/0.2 (research)"
KALSHI_BASES = [
    "https://external-api.kalshi.com/trade-api/v2",
    "https://api.elections.kalshi.com/trade-api/v2",
]
GAMMA = "https://gamma-api.polymarket.com"
MIN_VOL24 = 1000.0
MIN_OI = 2000.0
SLEEP = 0.25

TAGS: dict[str, re.Pattern[str]] = {
    "sec": re.compile(
        r"\b(SEC|EDGAR|Securities and Exchange Commission|8-K|10-Q|10-K|Form 4|S-1|424B\d?|"
        r"13D|13G|sec\.gov|prospectus|registration statement)\b"),
    "court": re.compile(
        r"\b(docket|court|ruling|judge|indictment|CourtListener|PACER|lawsuit|verdict|"
        r"Supreme Court|appeals|sentenced|convicted)\b", re.I),
    "fed_register": re.compile(r"\b(Federal Register|federalregister\.gov|Code of Federal)\b", re.I),
    "press_release": re.compile(
        r"\b(press release|official announcement|newsroom|investor relations|"
        r"official website|official statement|official blog)\b", re.I),
}


def get(url: str, params: dict[str, str | int] | None = None) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    last: Exception | None = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(2 ** attempt)
                last = e
                continue
            raise
        except urllib.error.URLError as e:
            time.sleep(2 ** attempt)
            last = e
    raise RuntimeError(f"GET failed: {url}: {last}")


def tags_in(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, pat in TAGS.items():
        m = pat.search(text)
        if m:
            out[name] = m.group(0)
    return out


def num(x: object) -> float:
    try:
        return float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def scan_kalshi(max_pages: int, stats: dict) -> list[dict]:
    base = None
    for b in KALSHI_BASES:
        try:
            get(f"{b}/events", {"status": "open", "limit": 1})
            base = b
            break
        except Exception as e:  # noqa: BLE001
            print(f"[kalshi] base {b} failed: {e}", file=sys.stderr)
    if base is None:
        raise RuntimeError("no Kalshi base URL worked")
    stats["kalshi_base"] = base
    out: list[dict] = []
    cursor = ""
    completed = False
    for page in range(max_pages):
        params: dict[str, str | int] = {"status": "open", "limit": 200, "with_nested_markets": "true"}
        if cursor:
            params["cursor"] = cursor
        data = get(f"{base}/events", params)
        for ev in data.get("events", []):
            stats["kalshi_events"] += 1
            cat = ev.get("category") or ""
            if cat == "Sports" or str(ev.get("series_ticker", "")).startswith("KXMVE"):
                stats["kalshi_excluded_events"] += 1
                continue
            src = [s.get("name") for s in ev.get("settlement_sources") or []]
            for m in ev.get("markets") or []:
                if m.get("status") not in (None, "active", "open", "initialized"):
                    continue
                stats["kalshi_markets"] += 1
                text = " ".join(str(m.get(k) or "") for k in ("rules_primary", "rules_secondary"))
                tg = tags_in(text)
                if not tg:
                    continue
                out.append({
                    "venue": "kalshi", "id": m.get("ticker"), "title": m.get("title") or ev.get("title"),
                    "event_title": ev.get("title"), "category": cat, "tags": tg,
                    "settlement_sources": src, "vol24": num(m.get("volume_24h_fp")),
                    "oi": num(m.get("open_interest_fp")), "liquidity": None,
                    "close": m.get("close_time"), "rules": text,
                })
        cursor = data.get("cursor") or ""
        if page % 5 == 0:
            print(f"[kalshi] page {page + 1} events_seen={stats['kalshi_events']}", file=sys.stderr)
        if not cursor:
            completed = True
            break
        time.sleep(SLEEP)
    stats["kalshi_completed"] = completed
    return out


def scan_poly(max_pages: int, stats: dict) -> list[dict]:
    out: list[dict] = []
    cursor = ""
    completed = False
    now = datetime.now(timezone.utc).isoformat()
    for page in range(max_pages):
        params: dict[str, str | int] = {"closed": "false", "active": "true", "archived": "false", "limit": 50}
        if cursor:
            params["after_cursor"] = cursor
        data = get(f"{GAMMA}/events/keyset", params)
        for ev in data.get("events", []):
            stats["poly_events"] += 1
            labels = [t.get("label") for t in ev.get("tags") or []]
            if any((l or "").lower() == "sports" for l in labels):
                stats["poly_excluded_events"] += 1
                continue
            for m in ev.get("markets") or []:
                if m.get("closed") or not m.get("acceptingOrders", True):
                    continue
                if m.get("comboStatus") == "enabled":
                    continue
                end = m.get("endDate") or ""
                if end and end < now:
                    stats["poly_expired_unresolved"] += 1
                    continue
                stats["poly_markets"] += 1
                text = " ".join(str(m.get(k) or "") for k in ("description", "resolutionSource"))
                tg = tags_in(text)
                if not tg:
                    continue
                out.append({
                    "venue": "polymarket", "id": m.get("conditionId") or m.get("id"),
                    "title": m.get("question"), "event_title": ev.get("title"), "category": None,
                    "poly_tags": labels, "tags": tg, "settlement_sources": [m.get("resolutionSource") or ""],
                    "vol24": num(m.get("volume24hr")), "oi": None,
                    "event_oi": num(ev.get("openInterest")),
                    "liquidity": num(m.get("liquidityNum") or m.get("liquidity")),
                    "close": end, "rules": text,
                })
        cursor = data.get("next_cursor") or ""
        if page % 5 == 0:
            print(f"[poly] page {page + 1} events_seen={stats['poly_events']}", file=sys.stderr)
        if not cursor:
            completed = True
            break
        time.sleep(SLEEP)
    stats["poly_completed"] = completed
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=3000)
    ap.add_argument("--out", default="slice_report.md")
    args = ap.parse_args()
    stats: dict = defaultdict(int)

    cands = scan_kalshi(args.max_pages, stats) + scan_poly(args.max_pages, stats)
    for c in cands:
        # Kalshi: vol24 or OI contracts; Polymarket: vol24 only (liquidity/event OI reported separately)
        c["meaningful"] = c["vol24"] >= MIN_VOL24 or (c["oi"] is not None and c["oi"] >= MIN_OI)

    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "slice_candidates.json").write_text(json.dumps(cands, indent=1), encoding="utf-8")

    by = defaultdict(lambda: [0, 0])
    for c in cands:
        for t in c["tags"]:
            by[(t, c["venue"])][0] += 1
            by[(t, c["venue"])][1] += int(c["meaningful"])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    L = [f"# Slice scan v2 ({now})", "",
         f"Kalshi base: `{stats.get('kalshi_base')}`; COMPLETED={stats['kalshi_completed']}; "
         f"events={stats['kalshi_events']} (excluded sports/mve={stats['kalshi_excluded_events']}); "
         f"open markets scanned={stats['kalshi_markets']}",
         f"Polymarket: COMPLETED={stats['poly_completed']}; events={stats['poly_events']} "
         f"(excluded sports={stats['poly_excluded_events']}); open markets scanned={stats['poly_markets']}; "
         f"skipped expired-unresolved={stats['poly_expired_unresolved']}",
         f"Meaningful (regex pass): vol24>={MIN_VOL24:.0f} OR Kalshi OI>={MIN_OI:.0f}. "
         "Polymarket liquidity / event OI NOT used; stored separately.", "",
         "| tag | venue | regex-matched | meaningful |", "|---|---|---|---|"]
    for (t, v), (n, nm) in sorted(by.items()):
        L.append(f"| {t} | {v} | {n} | {nm} |")
    L.append(f"\nTotal regex-matched: {len(cands)}; meaningful: {sum(c['meaningful'] for c in cands)}")
    Path(args.out).write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
