"""Build config/watch_allowlist_seed.json from the hand-reviewed DOC_SETTLED (strict) list.

Input: data/slice_classified.json (written by scripts/classify_slice.py; gitignored).
Output: config/watch_allowlist_seed.json (tracked). Every entry carries a reason and a reviewer.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVIEWER = "ai_assisted_slice_review_2026-11-13 (user-approved 2026-11-14)"


def main() -> None:
    rows = json.loads((ROOT / "data" / "slice_classified.json").read_text(encoding="utf-8"))
    entries: list[dict[str, str]] = [
        {
            "venue": "kalshi",
            "scope": "series",
            "key": "KXEOWEEK",
            "reason": "primary eval source: weekly executive orders settle on the Federal Register",
            "reviewer": "user decision 2026-11-14",
        }
    ]
    strat = json.loads(
        (ROOT / "fixtures/strategy_2026_05/polymarket_market_may31.json").read_text(
            encoding="utf-8"
        )
    )
    entries.append(
        {
            "venue": "polymarket",
            "scope": "market",
            "key": strat["conditionId"],
            "reason": "Strategy 'sells any BTC by May 31, 2026': required negative-test fixture "
            "(8-K accepted after the deadline; resolved No)",
            "reviewer": "user decision 2026-11-14",
        }
    )
    seen = {(e["venue"], e["scope"], e["key"]) for e in entries}
    for r in rows:
        if r["bucket"] != "DOC_SETTLED_STRICT":
            continue
        if r["venue"] == "kalshi" and r["id"].startswith("KXEOWEEK"):
            continue  # covered by the series entry
        k = (r["venue"], "market", r["id"])
        if k in seen:
            continue
        seen.add(k)
        entries.append(
            {
                "venue": r["venue"],
                "scope": "market",
                "key": r["id"],
                "reason": f"hand-reviewed DOC_SETTLED strict ({r['family']}): "
                f"{(r['event_title'] or r['title'])[:100]}",
                "reviewer": REVIEWER,
            }
        )
    out = ROOT / "config" / "watch_allowlist_seed.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        json.dumps({"version": 1, "entries": entries}, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out} with {len(entries)} entries")


if __name__ == "__main__":
    main()
