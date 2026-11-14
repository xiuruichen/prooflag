"""Serialization and markdown rendering for E2 results (deterministic)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from prooflag.edge.e2 import EventResult, Overall


def _f(x: float | None, nd: int = 3) -> str:
    if x is None:
        return "n/a"
    return "never" if x == float("inf") else f"{x:.{nd}f}"


def event_to_dict(e: EventResult) -> dict[str, Any]:
    return {
        "event": e.name,
        "t_doc": e.t_doc.isoformat(),
        "n_usable_counted": e.n_usable,
        "share_moved": round(e.share_moved, 6),
        "median_lag_minutes": None
        if e.median_lag_minutes != e.median_lag_minutes
        else ("inf" if e.median_lag_minutes == float("inf") else round(e.median_lag_minutes, 3)),
        "capacity_total": round(e.capacity_total, 2),
        "depth_total": round(e.depth_total, 2),
        "signal": e.signal,
        "markets": [
            {
                "id": m.market_id,
                "source": m.source,
                "usable": m.usable,
                "counted": m.counted,
                "p0": m.p0,
                "pA": m.pA,
                "p5": m.p5,
                "moved": m.moved,
                "pre_priced": m.pre_priced,
                "lag_minutes": m.lag_minutes,
                "capacity_net": round(m.capacity.net_profit, 2),
                "capacity_gross": round(m.capacity.gross_profit, 2),
                "depth_usd": round(m.depth_usd, 2),
            }
            for m in e.markets
        ],
    }


def render_markdown(
    events: dict[str, EventResult | None], ov: Overall, meta: dict[str, str]
) -> str:
    out = [f"### E2 verdict: **{ov.verdict}**   (PURSUE: {'yes' if ov.pursue else 'no'})", ""]
    out += [f"- {r}" for r in ov.reasons]
    out += ["", " ".join(f"{k}: {v}" for k, v in meta.items()), ""]
    for name, e in events.items():
        out.append(
            f"#### Event {name}: "
            + ("not observed" if e is None else f"t_doc {e.t_doc.isoformat()} - {e.signal}")
        )
        if e is None:
            continue
        out += [
            "",
            "| market | source | usable | counted | p0 | pA | p5 | moved | lag (min) | cap net $ | cap gross $ | depth $ |",  # noqa: E501
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for m in e.markets:
            out.append(
                f"| {m.market_id} | {m.source} | {m.usable} | {m.counted} | {_f(m.p0)} | {_f(m.pA)} | "  # noqa: E501
                f"{_f(m.p5)} | {m.moved} | {_f(m.lag_minutes, 1)} | {m.capacity.net_profit:,.2f} | "
                f"{m.capacity.gross_profit:,.2f} | {m.depth_usd:,.2f} |"
            )
        offs = [timedelta(minutes=1), timedelta(minutes=15), timedelta(hours=1), timedelta(hours=6)]
        out += [
            "",
            "Prices (resolved direction) after t_doc, median over counted markets: "
            + ", ".join(
                f"{lbl} {_f(_median([m.offsets.get(o) for m in e.markets if m.counted]))}"
                for o, lbl in zip(offs, ["+1m", "+15m", "+1h", "+6h"], strict=True)
            ),
            "",
        ]
    return "\n".join(out) + "\n"


def _median(vals: list[Any]) -> float | None:
    xs = sorted(v for v in vals if isinstance(v, float))
    if not xs:
        return None
    mid = len(xs) // 2
    return xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2
