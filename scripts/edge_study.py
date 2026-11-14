"""E1 edge study (offline): regenerate docs/edge-study.md from studies/e1/inputs/.

No network. Verdict rules are pre-registered in docs/dev-history/PLAN.md (E1 + Amendment A) and implemented in
prooflag.edge.stats. Hand-written commentary lives in studies/e1/interpretation.md.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from prooflag.edge.cases import (
    CEILING,
    MarketCase,
    Quote,
    analyze_market,
    eo_docs_from_inputs,
    read_gz,
    summarize_weeks,
)
from prooflag.edge.eo import parse_rule
from prooflag.edge.fees import kalshi_fee, polymarket_taker_fee
from prooflag.edge.ipo import reaction
from prooflag.edge.report import bucket_table, ci, dist, f, md_table, money, offsets_table, ts
from prooflag.edge.stats import (
    MIN_CAPACITY_USD,
    MIN_LAG_MINUTES,
    MIN_WEEKS,
    PNL_UPPER_FLOOR,
    SHARE_PRICE_LED,
    quantile,
)
from prooflag.ingest.models import Trade

ROOT = Path(__file__).resolve().parent.parent
IN = ROOT / "studies" / "e1" / "inputs"


def load_trades(raw: dict[str, list[list[Any]]]) -> dict[str, list[Trade]]:
    out: dict[str, list[Trade]] = {}
    for tk, rows in raw.items():
        ts_ = [
            Trade(datetime.fromisoformat(r[0]), float(r[1]), float(r[2]), r[3], r[4]) for r in rows
        ]
        out[tk] = sorted(ts_, key=lambda t: (t.ts, t.trade_id))
    return out


def load_quotes(raw: dict[str, list[list[Any]]]) -> dict[str, list[Quote]]:
    return {
        tk: sorted(
            (Quote(datetime.fromisoformat(r[0]), r[1], r[2]) for r in rows), key=lambda q: q.ts
        )
        for tk, rows in raw.items()
    }


def strategy_section(data: dict[str, Any]) -> str:
    hist = next((v for k, v in sorted(data["history"].items(), key=lambda kv: int(kv[0])) if v), [])
    pts = [(datetime.fromtimestamp(h["t"], UTC), float(h["p"])) for h in hist]
    t_doc = datetime(2026, 6, 1, 12, 0, 16, tzinfo=UTC)

    def at(t: datetime) -> float | None:
        prior = [p for (tt, p) in pts if tt <= t and t - tt <= timedelta(hours=24)]
        return prior[-1] if prior else None

    rows = []
    for label, off in [
        ("-5 min", timedelta(minutes=-5)),
        ("-3 min", timedelta(minutes=-3)),
        ("-1 min", timedelta(minutes=-1)),
        ("t_doc", timedelta(0)),
        ("+1 min", timedelta(minutes=1)),
        ("+2 min (buy)", timedelta(minutes=2)),
        ("+15 min", timedelta(minutes=15)),
        ("+1 h", timedelta(hours=1)),
        ("+6 h", timedelta(hours=6)),
    ]:
        rows.append([label, ts(t_doc + off), f(at(t_doc + off))])
    mx = max(((p, tt) for tt, p in pts if tt >= t_doc), default=None)
    first90 = next((tt for tt, p in pts if tt >= t_doc and p >= 0.90), None)
    buy = at(t_doc + timedelta(minutes=2))
    rate = (data.get("fee_schedule") or {}).get("rate", 0.0)
    fee = polymarket_taker_fee(100, buy, rate) if buy is not None else None
    pnl = None if buy is None or fee is None else -100 * buy - fee  # resolved No: YES worth 0
    return (
        f"Case: Polymarket 'MicroStrategy sells any Bitcoin by May 31, 2026?' (resolved **No**). "
        f"t_doc = EDGAR acceptance of 8-K 0001193125-26-249768, 2026-06-01 12:00:16Z (08:00:16 ET), "
        f"about 8 h after the 23:59 ET May 31 deadline. The filing reports 32 BTC sold May 26-31. "
        f"Price source: CLOB prices-history ({len(pts)} points; one price per point, **no bid/ask**), "
        f"so everything here is **price-based** and is excluded from the pooled verdict.\n\n"
        + md_table(["moment", "time", "YES price"], rows)
        + f"\n\nPeak after t_doc: {f(mx[0] if mx else None)} at {ts(mx[1] if mx else None)}; "
        f"first price >= 0.90 after t_doc: {ts(first90)} (never reached if n/a). "
        f"Naive rule 'buy YES at t_doc + 2 min' at {f(buy)}: the market resolved No (the filing "
        f"satisfied the content of the rule but not the deadline basis), so 100 contracts lose "
        f"about {money(None if pnl is None else -pnl)} including the Polymarket taker fee "
        f"(rate {rate}, formula C x rate x p x (1-p) = {money(fee)}). "
        f"**The document implied Yes; the market resolved No: this is the case evidence_gap must "
        f"suppress** (deadline_applies_to ambiguous). Note the price was already rising BEFORE the "
        f"filing was accepted (see the -5/-3/-1 min rows): the market reacted to Strategy's own "
        f"announcement channel a few minutes ahead of EDGAR, so even for an EDGAR-settled market the "
        f"filing itself was not the first public signal."
    )


def family_section(rows: list[dict[str, Any]], ipo: dict[str, Any]) -> str:
    def fam(r: dict[str, Any]) -> str:
        reason = (r.get("reason") or "").lower()
        if "primary eval" in reason:
            return "weekly executive orders (KXEOWEEK)"
        if "strategy" in reason:
            return "Strategy fixture"
        for key, label in (
            ("(sec)", "SEC / EDGAR"),
            ("(federal_register)", "Federal Register"),
            ("(court/agency)", "court / agency"),
        ):
            if key in reason:
                return label
        return "other"

    c: dict[tuple[str, str], Counter[str]] = {}
    for r in rows:
        c.setdefault((fam(r), r["venue"]), Counter())[r["status"]] += 1
    table = md_table(
        ["family", "venue", "watched markets", "open", "past_end", "settled"],
        [
            [k[0], k[1], sum(v.values()), v["open"], v["past_end"], v["settled"]]
            for k, v in sorted(c.items())
        ],
    )
    return (
        table
        + "\n\nNo allow-listed SEC, Federal Register (non-weekly) or court market has resolved yet, "
        "so none has a measurable settling-document timestamp: **0 resolved cases** (INSUFFICIENT DATA "
        "for those families). The IPO family's settling documents are pending (see the IPO section). "
        "Court markets: no resolved case, and no docket-timestamp source is built yet (CourtListener is "
        "the first post-MVP milestone)."
    )


def ipo_section(d: dict[str, Any]) -> str:
    from prooflag.edge.cases import read_gz as _rg  # noqa: F401

    series: dict[str, list[Trade]] = {}
    for tk, v in d["kalshi"].items():
        series[f"K:{tk}"] = sorted(
            (
                Trade(datetime.fromisoformat(r[0]), float(r[1]), float(r[2]), r[3], r[4])
                for r in v["trades"]
            ),
            key=lambda t: t.ts,
        )
    for mid, v in d["polymarket"].items():
        series[f"P:{mid[:10]}"] = [
            Trade(datetime.fromisoformat(p[0]), float(p[1]), 1.0, "", f"{mid}-{i}")
            for i, p in enumerate(v["points"])
            if p[1] is not None
        ]
    keep = {"S-1", "S-1/A", "424B4", "EFFECT", "424B1", "FWP", "8-A12B", "DRS", "DRS/A"}
    filings = sorted(
        (x for x in d["filings"] if x["form"] in keep and x["filing_date"] >= "2026-10-20"),
        key=lambda x: x["accepted_utc"],
    )
    out = [
        f"{d['name']} (CIK {d['cik']}, ticker {d['tickers']}) **has already filed publicly on EDGAR**: "
        f"{len(d['filings'])} filings since 2026-06-01 (DRS drafts, then the public S-1 on "
        f"2026-10-26, S-1/A amendments, FWPs). The settling documents for the IPO markets (SEC "
        f"effectiveness, 424B pricing) are therefore pending, not absent. Markets: "
        f"{sum(k.startswith('K:') for k in series)} Kalshi (KXIPOANTHROPIC, trades) and "
        f"{sum(k.startswith('P:') for k in series)} Polymarket (CLOB, 10-minute prices). "
        "This is ONE correlated cluster and the filings are leading, not settling, documents, so the "
        "table is descriptive and outside the verdict. Entries are the median change in YES price "
        "from the price at filing acceptance.\n"
    ]
    rows = []
    for fl in filings:
        t = datetime.fromisoformat(fl["accepted_utc"].replace("Z", "+00:00"))
        r = reaction(series, t)
        cells = [
            f"{x.median_change:+.3f} / {x.mean_abs_change:.3f} (n={x.n})"
            if x.median_change is not None and x.mean_abs_change is not None
            else "n/a"
            for x in r.rows
        ]
        rows.append([fl["form"], ts(t), r.n_markets, *cells])
    out.append(
        md_table(
            [
                "form",
                "accepted",
                "markets priced",
                "-1 h",
                "+1 min",
                "+15 min",
                "+1 h",
                "+6 h",
                "+24 h",
            ],
            rows,
        )
    )
    return "\n".join(out)


def main() -> None:
    markets = read_gz(IN / "kalshi_markets.json.gz")
    trades = load_trades(read_gz(IN / "kalshi_trades.json.gz"))
    quotes = load_quotes(read_gz(IN / "kalshi_candles.json.gz"))
    eo_rows = read_gz(IN / "fr_eos.json.gz")
    eos, pi_stats = eo_docs_from_inputs(eo_rows)
    manifest = read_gz(IN / "manifest.json.gz")
    fee_info = read_gz(IN / "kalshi_fee_info.json.gz")
    fee_type = str(fee_info.get("fee_type"))
    fee_mult = float(fee_info.get("fee_multiplier") or 1.0)

    def fee_fn(count: float, price: float) -> float:
        # raises UnsupportedFeeTypeError for flat / unknown series fee types: never guessed
        return kalshi_fee(fee_type, fee_mult, count, price)

    cases: list[MarketCase] = []
    unparsed: list[str] = []
    for m in markets:
        rule = parse_rule(m["rules_primary"])
        if rule is None:
            unparsed.append(m["ticker"])
            continue
        cases.append(
            analyze_market(
                m, rule, eos, trades.get(m["ticker"], []), quotes.get(m["ticker"], []), fee_fn
            )
        )

    summ_pi = summarize_weeks(cases, "pi")
    summ_pub = summarize_weeks(cases, "pub")
    elig = [c for c in cases if c.eligible]
    mism = [c for c in cases if not c.validated]
    reasons = Counter(c.excluded_reason for c in cases if not c.eligible)
    by_result = Counter(c.recorded for c in cases)
    close_days = [float(c.close_vs_pub_days) for c in elig if c.close_vs_pub_days is not None]

    lines: list[str] = []
    w = lines.append
    w("# E1 Edge study: do prediction markets lag public documents enough to trade on?\n")
    w(
        f"Generated offline from `studies/e1/inputs/` (fetched {manifest['fetched_at']}, code "
        f"`{manifest['code_git_sha'][:10]}`) by `scripts/edge_study.py`. Pre-registered rules: docs/dev-history/PLAN.md "
        "section 10d (E1 + Amendment A). The verdict below is computed by code from those rules; "
        "the commentary at the end is hand-written and post-hoc.\n"
    )
    w("## Verdict (weekly executive-order markets, public-inspection basis)\n")
    w(f"### **{summ_pi.verdict_label}**\n")
    for r in summ_pi.verdict_reasons:
        w(f"- {r}")
    w("")
    w(
        md_table(
            ["quantity", "value"],
            [
                [
                    "independent units (weeks) usable",
                    f"{summ_pi.n_weeks_usable} (rule: >= {MIN_WEEKS})",
                ],
                ["Yes-implied markets in those weeks", summ_pi.n_markets_eligible],
                [
                    "share of weeks with price already >= 0.90 at the posting",
                    f"{summ_pi.share_led:.0%} (Wilson 95% [{summ_pi.share_led_ci[0]:.0%}, "
                    f"{summ_pi.share_led_ci[1]:.0%}]; rule: >= {SHARE_PRICE_LED:.0%} means no edge)",
                ],
                ["after-fee P&L per contract, buy YES at ask t+2 min (weeks)", ci(summ_pi.pnl_ci)],
                [
                    "weeks with a usable ask (P&L defined)",
                    f"{summ_pi.n_weeks_with_ask} of {summ_pi.n_weeks_usable} "
                    "(most thin markets have no quote within 24 h of the posting; the primary P&L rests on these weeks only)",
                ],
                ["same, fee-free sensitivity", ci(summ_pi.pnl_free_ci)],
                [
                    "sensitivity: buy at LAST TRADE price (no spread) at t+2 min, after fees "
                    f"({summ_pi.n_weeks_with_price_buy} weeks)",
                    ci(summ_pi.pnl_price_ci),
                ],
                [
                    "lag: first sustained 0.90 minus posting, minutes (weeks)",
                    dist(
                        [
                            x
                            for x in [wk.median_lag90 for wk in summ_pi.weeks if wk.usable]
                            if x is not None
                        ]
                    )
                    + f" (rule: median >= {MIN_LAG_MINUTES:.0f} min)",
                ],
                [
                    "median per-week capacity (after-fee profit available below 0.95)",
                    f"{money(summ_pi.capacity_median)} (rule: >= ${MIN_CAPACITY_USD:.0f})",
                ],
                ["upper-bound floor for 'no edge'", f"${PNL_UPPER_FLOOR}"],
            ],
        )
    )
    w(
        "\nFees: Kalshi per the standard schedule (confirmed by the author 2026-11-14): taker fee = "
        "round_up_to_cent(0.07 x multiplier x C x p x (1-p)) per order (100 contracts here); maker fee on "
        "maker-fee series round_up_to_cent(0.0175 x multiplier x C x p x (1-p)); the series fee type is read "
        "from the API and unsupported types (flat, unknown) raise instead of being guessed. This series: "
        f"{fee_info.get('fee_type')}, multiplier x{fee_info.get('fee_multiplier')}. Polymarket per "
        "docs.polymarket.com/trading/fees (taker only). The fee-free row shows the effect of fees.\n"
    )

    w("## Data and validation\n")
    w(
        f"- Resolved KXEOWEEK markets analysed: {len(cases)} (yes {by_result['yes']}, no "
        f"{by_result['no']}); unparsed rules: {len(unparsed)} {unparsed[:3]}."
    )
    w(
        f"- Federal Register executive orders: {len(eos)} (signing >= 2025-08-01); public-inspection "
        f"time source: API {pi_stats['pi_api']}, URL-timestamp fallback {pi_stats['pi_url_fallback']}, "
        f"missing {pi_stats['pi_missing']}."
    )
    w(
        f"- **Method validation:** computed result (count of in-window EOs by FR signing date, de-duplicated "
        f"by EO number) equals the venue's recorded result for {len(cases) - len(mism)}/{len(cases)} markets."
        + (
            " Mismatches: "
            + ", ".join(
                f"{c.ticker} (computed {c.implied}, recorded {c.recorded})" for c in mism[:12]
            )
            if mism
            else ""
        )
    )
    w(f"- Yes market close date minus deciding-EO publication date (days): {dist(close_days)}.")
    w(
        "- Exclusions from the Yes-implied sample: "
        + "; ".join(f"{k or 'eligible'}: {v}" for k, v in reasons.most_common())
        + ".\n"
    )

    w("## Key question: public inspection or official publication?\n")
    w(
        "First sustained trade at or above 0.90, relative to the deciding EO's signing date (00:00 ET), "
        "public-inspection posting and publication (06:00 ET, assumed). Weeks use the modal bucket of "
        "their markets.\n"
    )
    w(bucket_table(summ_pi, cases))
    w("")
    share_pi = [c.pi.share_of_jump for c in elig if c.pi.share_of_jump is not None]
    share_pub = [c.pub.share_of_jump for c in elig if c.pub.share_of_jump is not None]
    w(
        f"Share of the final jump (week-start price to 1.0) already realized at the posting: "
        f"public inspection {dist(share_pi, 2)}; official publication {dist(share_pub, 2)}.\n"
    )
    w("Last traded price relative to the public-inspection posting:\n")
    w(offsets_table(elig, "pi"))
    w("\nRelative to official publication:\n")
    w(offsets_table(elig, "pub"))
    lag_pub = [
        wk.median_lag90 for wk in summ_pub.weeks if wk.usable and wk.median_lag90 is not None
    ]
    w(f"\nLag of first sustained 0.90 versus publication (minutes, weeks): {dist(lag_pub)}.\n")

    w("## Dollar capacity\n")
    caps = [(wk.week, wk.capacity_net) for wk in summ_pi.weeks if wk.usable]
    w(
        f"After-fee profit a taker could have captured by buying all YES volume that traded below "
        f"{CEILING} after posting + 2 min: median {money(quantile([c for _, c in caps], 0.5)) if caps else 'n/a'} "
        f"per week, total {money(sum(c for _, c in caps))} over {len(caps)} weeks.\n"
    )

    w("## Per-week table (public-inspection basis)\n")
    w(
        md_table(
            [
                "week",
                "markets",
                "price led?",
                "median lag 0.90 (min)",
                "mean P&L/contract",
                "capacity",
            ],
            [
                [
                    wk.week,
                    wk.n_markets,
                    "yes" if wk.led else "no",
                    f(wk.median_lag90, 1),
                    f(wk.mean_pnl, 4),
                    money(wk.capacity_net),
                ]
                for wk in summ_pi.weeks
            ],
        )
    )
    lagged = [wk for wk in summ_pi.weeks if wk.usable and not wk.led]
    w("\n## Weeks where the price did NOT already lead the posting\n")
    if lagged:
        w(
            md_table(
                ["week", "median lag 0.90 (min)", "capacity (after-fee profit below 0.95)"],
                [[wk.week, f(wk.median_lag90, 1), money(wk.capacity_net)] for wk in lagged],
            )
        )
        w(
            f"\n{len(lagged)} of {summ_pi.n_weeks_usable} weeks. These carry all of the dollar capacity in the "
            "sample (the per-week median is $0). They are listed so the heavy tail is visible; with n this "
            "small it cannot be called a pattern, and the chronology is noted in the interpretation.\n"
        )
    else:
        w("None.\n")
    w("\n## Per-market table\n")
    w(
        md_table(
            [
                "market",
                "t_pi",
                "price@pi",
                "lag 0.90 (min)",
                "bucket",
                "ask@pi+2m",
                "P&L/contract",
                "close-pub days",
            ],
            [
                [
                    c.ticker,
                    ts(c.pi.t_doc),
                    f(c.pi.price_at),
                    f(c.pi.lag90_minutes, 1),
                    c.pi.bucket90,
                    f(c.pi.ask),
                    f(c.pi.pnl_per_contract, 4),
                    c.close_vs_pub_days,
                ]
                for c in elig
            ],
        )
    )

    w("\n## IPO family (one cluster, descriptive): reaction to EDGAR filings\n")
    w(ipo_section(read_gz(IN / "ipo_cluster.json.gz")))
    w("\n## Other families\n")
    fam_rows = read_gz(IN / "allowlist_status.json.gz")
    ipo = read_gz(IN / "edgar_ipo_check.json.gz")
    w(family_section(fam_rows, ipo))
    w("\n## Strategy case (price-based, outside the pooled verdict)\n")
    w(strategy_section(read_gz(IN / "strategy_prices.json.gz")))

    interp = ROOT / "studies" / "e1" / "interpretation.md"
    w("\n## Interpretation and what to build next (hand-written, post-hoc)\n")
    w(interp.read_text(encoding="utf-8") if interp.exists() else "_Not yet written._\n")
    e2 = ROOT / "studies" / "e2" / "preregistration.md"
    if e2.exists():
        w("\n## E2 pre-registration (live test on the Anthropic IPO filings)\n")
        w(e2.read_text(encoding="utf-8"))
    w("\n## Limitations\n")
    w(
        "- Weekly-EO markets only; other families have no resolved cases (see above).\n"
        "- t_pub = 06:00 ET on the publication date is an assumption; PI times come from the FR API "
        "(or the URL timestamp fallback).\n"
        "- Trades give exact times and sizes; bid/ask come from hourly candles carried forward, so the buy "
        "price at t+2 min can be up to 24 h stale (pre-registered limit). Thin markets: absolute numbers are small.\n"
        "- Kalshi fees: standard schedule confirmed by the author (2026-11-14); results are also shown fee-free.\n"
        "- The deciding-document logic assumes the venue resolves strictly by FR signing date, which the "
        "validation row above tests market by market.\n"
    )
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "edge-study.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote docs/edge-study.md;", summ_pi.verdict_label)
    print(
        json.dumps(
            {
                "weeks_usable": summ_pi.n_weeks_usable,
                "eligible_markets": len(elig),
                "validated": f"{len(cases) - len(mism)}/{len(cases)}",
            }
        )
    )


if __name__ == "__main__":
    main()
