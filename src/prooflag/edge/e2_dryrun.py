"""Offline dry run of the E2 pipeline on E1 data (weekly EO, Anthropic S-1) and Strategy.

Not a verdict about Anthropic: it exercises the pre-registered code on real recorded data so
the live run can be trusted. Output is committed as tests/fixtures/e2/dryrun.json.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prooflag.edge.cases import eo_docs_from_inputs, read_gz
from prooflag.edge.e2 import E2Market, analyze_event, overall
from prooflag.edge.e2_report import event_to_dict
from prooflag.edge.eo import deciding_eo, dedupe, in_window, parse_rule
from prooflag.edge.fees import kalshi_fee
from prooflag.ingest.models import Trade

ROOT = Path(__file__).resolve().parents[3]
E1 = ROOT / "studies" / "e1" / "inputs"
WEEKS = ("KXEOWEEK-26AUG08", "KXEOWEEK-26SEP19", "KXEOWEEK-26JUN06", "KXEOWEEK-26MAY30")


def _trades(rows: list[list[Any]]) -> list[Trade]:
    ts = (Trade(datetime.fromisoformat(r[0]), float(r[1]), float(r[2]), r[3], r[4]) for r in rows)
    return sorted(ts, key=lambda t: (t.ts, t.trade_id))


def run(e1_dir: Path = E1) -> dict[str, Any]:
    markets = {m["ticker"]: m for m in read_gz(e1_dir / "kalshi_markets.json.gz")}
    trades = read_gz(e1_dir / "kalshi_trades.json.gz")
    eos, _ = eo_docs_from_inputs(read_gz(e1_dir / "fr_eos.json.gz"))
    docs = dedupe(eos)
    fee = read_gz(e1_dir / "kalshi_fee_info.json.gz")

    def fee_fn(c: float, p: float) -> float:
        return kalshi_fee(str(fee["fee_type"]), float(fee.get("fee_multiplier") or 1.0), c, p)

    out: dict[str, Any] = {"weekly_eo_events": [], "note": "dry run: not an Anthropic result"}
    events = {}
    for wk in WEEKS:
        wk_markets = [
            m for t, m in markets.items() if m["event_ticker"] == wk and m["result"] == "yes"
        ]
        e2m, t_doc = [], None
        for m in wk_markets:
            rule = parse_rule(m["rules_primary"])
            if rule is None or rule.needed is None:
                continue
            dec = deciding_eo(rule, in_window(docs, rule.start, rule.end), "pi")
            if dec is None or dec.pi_filed_at is None:
                continue
            t_doc = dec.pi_filed_at.astimezone(UTC)
            close = datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
            e2m.append(
                E2Market(
                    m["ticker"],
                    "kalshi",
                    "yes",
                    _trades(trades[m["ticker"]]),
                    "trades",
                    fee_fn,
                    close,
                )
            )
        if t_doc is not None:
            ev = analyze_event(wk, t_doc, e2m)
            events[wk] = ev
            out["weekly_eo_events"].append(event_to_dict(ev))
    out["overall_if_these_were_the_events"] = overall(dict(list(events.items())[:2])).verdict
    # Liquid real data: the Anthropic S-1 / S-1/A filings (leading, not settling, documents) with all  # noqa: E501
    # IPO-cluster markets treated as direction 'yes'. Exercises the verdict path; fees ignored.
    ipo = read_gz(e1_dir / "ipo_cluster.json.gz")
    nofee = lambda c, p: 0.0  # noqa: E731
    ipo_markets: list[E2Market] = [
        E2Market(f"K:{tk}", "kalshi", "yes", _trades(v["trades"]), "trades", nofee, None)
        for tk, v in sorted(ipo["kalshi"].items())
    ] + [
        E2Market(
            f"P:{mid[:10]}",
            "polymarket",
            "yes",
            [
                Trade(datetime.fromisoformat(p[0]), float(p[1]), 1.0, "", f"{mid}-{i}")
                for i, p in enumerate(v["points"])
                if p[1] is not None
            ],
            "clob",
            nofee,
            None,
        )
        for mid, v in sorted(ipo["polymarket"].items())
    ]
    ipo_events = {}
    for name, ts in (
        ("S-1", "2026-10-26T13:00:11+00:00"),
        ("S-1/A-1", "2026-11-02T14:24:24+00:00"),
        ("S-1/A-2", "2026-11-10T11:29:24+00:00"),
    ):
        ipo_events[name] = analyze_event(name, datetime.fromisoformat(ts), ipo_markets)
    out["anthropic_s1_dryrun_events"] = [event_to_dict(e) for e in ipo_events.values()]
    out["anthropic_s1_dryrun_overall"] = overall(
        {"A": ipo_events["S-1"], "B": ipo_events["S-1/A-2"]}
    ).verdict
    strat = read_gz(E1 / "strategy_prices.json.gz")
    hist = next(v for k, v in sorted(strat["history"].items(), key=lambda kv: int(kv[0])) if v)
    pts = [
        Trade(datetime.fromtimestamp(h["t"], UTC), float(h["p"]), 1.0, "", f"s{i}")
        for i, h in enumerate(hist)
    ]
    sm = E2Market("strategy-may31", "polymarket", "no", pts, "clob", lambda c, p: 0.0, None)
    sev = analyze_event("strategy", datetime(2026, 6, 1, 12, 0, 16, tzinfo=UTC), [sm])
    out["strategy"] = event_to_dict(sev)
    return out


if __name__ == "__main__":
    dest = ROOT / "tests" / "fixtures" / "e2" / "dryrun.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(run(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("wrote", dest)
