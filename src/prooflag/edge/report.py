"""Markdown rendering helpers for docs/edge-study.md."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from prooflag.edge.cases import BUCKETS, MarketCase, Summary
from prooflag.edge.stats import quantile


def md_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def f(x: float | None, nd: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def money(x: float | None) -> str:
    return "n/a" if x is None else f"${x:,.2f}"


def ts(t: datetime | None) -> str:
    return "n/a" if t is None else t.astimezone(UTC).strftime("%Y-%m-%d %H:%MZ")


def dist(xs: Sequence[float], nd: int = 1) -> str:
    if not xs:
        return "n/a (n=0)"
    return (
        f"median {quantile(xs, 0.5):.{nd}f} [p25 {quantile(xs, 0.25):.{nd}f}, "
        f"p75 {quantile(xs, 0.75):.{nd}f}] (n={len(xs)})"
    )


def ci(t: tuple[float, float, float] | None, nd: int = 4) -> str:
    return "n/a" if t is None else f"mean ${t[0]:.{nd}f}, 95% CI [${t[1]:.{nd}f}, ${t[2]:.{nd}f}]"


def offsets_table(cases: Sequence[MarketCase], basis: str) -> str:
    offs = [timedelta(minutes=1), timedelta(minutes=15), timedelta(hours=1), timedelta(hours=6)]
    labels = ["+1 min", "+15 min", "+1 h", "+6 h"]
    rows = []
    for o, label in zip(offs, labels, strict=True):
        vals, na, none = [], 0, 0
        for c in cases:
            r = c.pi if basis == "pi" else c.pub
            v = r.offsets.get(o)
            if v == "NA":
                na += 1
            elif v is None:
                none += 1
            elif isinstance(v, float):
                vals.append(v)
        rows.append([label, dist(vals, 3), na, none])
    return md_table(
        [
            "offset from posting",
            "last traded price (median [p25, p75], n)",
            "N/A (market closed)",
            "no trade in 24 h",
        ],
        rows,
    )


def bucket_table(summary: Summary, cases: Sequence[MarketCase]) -> str:
    mk = dict.fromkeys(BUCKETS, 0)
    for c in cases:
        if c.eligible:
            mk[c.pi.bucket90] += 1
    wk = dict.fromkeys(BUCKETS, 0)
    for w in summary.weeks:
        if w.usable:
            top = max(BUCKETS, key=lambda b: (w.buckets[b], -BUCKETS.index(b)))
            wk[top] += 1
    n_m, n_w = sum(mk.values()), sum(wk.values())
    rows = [
        [
            b,
            mk[b],
            f"{mk[b] / n_m:.0%}" if n_m else "n/a",
            wk[b],
            f"{wk[b] / n_w:.0%}" if n_w else "n/a",
        ]
        for b in BUCKETS
    ]
    return md_table(
        ["first SUSTAINED trade >= 0.90 occurs ...", "markets", "%", "weeks (modal)", "%"], rows
    )
