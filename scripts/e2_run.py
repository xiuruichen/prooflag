"""E2: run the pre-registered analysis (one command). Applies studies/e2/preregistration.md exactly.

Usage: uv run python scripts/e2_run.py            (finds the events in EDGAR, fetches prices, writes results)
Writes studies/e2/results.md and results.json (appended to docs/edge-study.md by scripts/edge_study.py).
Needs PROOFLAG_CONTACT_EMAIL (SEC) and network. Exits 0 with "not observed" while an event has not happened.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from prooflag.clock import SystemClock
from prooflag.config import Settings
from prooflag.edge.e2 import E2Market, EventResult, analyze_event, overall
from prooflag.edge.e2_live import classify_market, find_events
from prooflag.edge.e2_report import event_to_dict, render_markdown
from prooflag.edge.fees import kalshi_fee, polymarket_taker_fee
from prooflag.ingest.http import VenueClient
from prooflag.ingest.kalshi import KalshiSource
from prooflag.ingest.models import Trade
from prooflag.ingest.polymarket import PolymarketSource
from prooflag.sec_client import SecClient

ROOT = Path(__file__).resolve().parent.parent
CIK = "0002130357"
SETTLE_WAIT = timedelta(hours=24)  # capacity window is t_doc+24 h; wait for complete history


def sec_filings(settings: Settings) -> list[tuple[str, datetime]]:
    c = SecClient(user_agent=settings.user_agent, max_rps=settings.sec_max_rps)
    sub = c.get_json(f"https://data.sec.gov/submissions/CIK{CIK}.json")
    r = sub["filings"]["recent"]
    return [
        (
            r["form"][i],
            datetime.fromisoformat(r["acceptanceDateTime"][i].replace("Z", "+00:00")).astimezone(
                UTC
            ),
        )
        for i in range(len(r["form"]))
    ]


def candidate_markets(settings: Settings) -> list[dict[str, Any]]:
    """Anthropic IPO-cluster markets in the local DB (venue, id, title, series, status, result)."""
    c = sqlite3.connect(settings.db_path)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "select venue, market_id, title, series_ticker, status, result, close_time_utc, yes_label from markets"
        " where (cluster_id='issuer_ipo_family' or series_ticker in ('KXIPOANTHROPIC','KXANTHROPICLEADLEFT'))"
        " and (lower(title) like '%anthropic%' or series_ticker like 'KX%ANTHROPIC%')"
    ).fetchall()
    return [dict(r) for r in rows]


def main() -> None:
    settings = Settings()
    settings.require_real_contact()
    now = SystemClock().now()
    filings = sec_filings(settings)
    t_a, b = find_events(filings)
    events: dict[str, EventResult | None] = {"A": None, "B": None}
    meta = {
        "checked_at": now.isoformat(),
        "cik": CIK,
        "t_A": t_a.isoformat() if t_a else "not observed",
        "t_B": b[1].isoformat() if b else "not observed",
    }
    vc = VenueClient(user_agent=settings.venue_user_agent, max_rps=settings.venue_max_rps)
    kal = KalshiSource(vc, settings.kalshi_base)
    pm = PolymarketSource(
        vc, settings.gamma_base, settings.clob_base, data_base=settings.poly_data_base
    )
    cands = candidate_markets(settings)
    fee_cache: dict[str, Any] = {}

    def kalshi_fee_fn(series: str) -> Any:
        if series not in fee_cache:
            s = vc.get_json(f"{settings.kalshi_base}/series/{series}")
            s = s.get("series", s)
            fee_cache[series] = (str(s.get("fee_type")), float(s.get("fee_multiplier") or 1.0))
        ft, mult = fee_cache[series]
        return lambda c, p: kalshi_fee(ft, mult, c, p)

    for name, t_doc in (("A", t_a), ("B", b[1] if b else None)):
        if t_doc is None:
            continue
        if now - t_doc < SETTLE_WAIT:
            meta[f"event_{name}"] = "too early: waiting for post-event trade history"
            continue
        markets: list[E2Market] = []
        for m in cands:
            if classify_market(m["venue"], m["series_ticker"], m["title"]) != name:
                continue
            if m["close_time_utc"] and datetime.fromisoformat(m["close_time_utc"]) < t_doc:
                continue  # pre-registered: market must be open at t_doc
            if m.get("yes_label") not in (None, "Yes"):
                continue  # plain Yes/No markets only
            if name == "A":
                direction = "yes"
            elif m["result"] in ("yes", "no"):
                direction = m["result"]
            else:
                continue  # B: direction is the recorded resolution; unsettled markets wait
            if m["venue"] == "kalshi":
                tr, src = kal.all_trades(m["market_id"]), "trades"
                fee = kalshi_fee_fn(m["series_ticker"])
            else:
                rms = pm.fetch_markets([m["market_id"]])
                try:
                    tr, src = list(pm.iter_trades(m["market_id"])), "trades"
                except Exception:
                    tr, src = [], "clob"
                    tok = rms[0].token_ids.get("yes") if rms else None
                    st = t_doc - timedelta(hours=24)
                    for fid in (1, 5, 10):
                        try:
                            pts = pm.price_history(tok or "", st, t_doc + timedelta(hours=26), fid)
                        except Exception:
                            continue
                        tr = [
                            Trade(p.ts, p.price, 1.0, "", f"clob-{p.ts.timestamp()}")
                            for p in pts
                            if p.price is not None
                        ]
                        break
                rate = 0.0
                for rm in rms:
                    rate = float((rm.raw.get("feeSchedule") or {}).get("rate") or 0.0)
                fee = (lambda r: lambda c, p: polymarket_taker_fee(c, p, r))(rate)
            tr = sorted(tr, key=lambda t: (t.ts, t.trade_id))
            close = datetime.fromisoformat(m["close_time_utc"]) if m["close_time_utc"] else None
            markets.append(E2Market(m["market_id"], m["venue"], direction, tr, src, fee, close))
        events[name] = analyze_event(name, t_doc, markets)
    ov = overall(events)
    out = ROOT / "studies" / "e2"
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.md").write_text(render_markdown(events, ov, meta), encoding="utf-8")
    (out / "results.json").write_text(
        json.dumps(
            {
                "meta": meta,
                "verdict": ov.verdict,
                "pursue": ov.pursue,
                "events": {k: (event_to_dict(e) if e else None) for k, e in events.items()},
            },
            indent=1,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(ov.verdict, "| pursue:", ov.pursue, "|", meta)


if __name__ == "__main__":
    main()
