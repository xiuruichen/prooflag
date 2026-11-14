"""E2 live helpers (pure): find the two pre-registered events and classify markets BEFORE prices."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime

A_FORMS = ("EFFECT",)
B_FORMS = ("424B4", "424B1", "424B3")
_B_TITLE = re.compile(
    r"IPO valuation|raise .* in its IPO|sold in its IPO|lead-left|serve as lead", re.I
)


def find_events(
    filings: Sequence[tuple[str, datetime]],
) -> tuple[datetime | None, tuple[str, datetime] | None]:
    """(t_A, (form, t_B)) from (form, acceptance UTC) rows. A = the first EFFECT; B = the first
    424B4 / 424B1 / 424B3 accepted after A (None while either has not occurred)."""
    effects = sorted(t for f, t in filings if f in A_FORMS)
    if not effects:
        return None, None
    t_a = effects[0]
    after = sorted((t, f) for f, t in filings if f in B_FORMS and t > t_a)
    return t_a, ((after[0][1], after[0][0]) if after else None)


def classify_market(venue: str, series_ticker: str | None, title: str) -> str | None:
    """'A' (settles on effectiveness), 'B' (settles on the final prospectus) or None. Decided from
    series / rule wording only, never from prices."""
    if "anthropic" not in title.lower() and series_ticker not in (
        "KXIPOANTHROPIC",
        "KXANTHROPICLEADLEFT",
    ):
        return None
    if venue == "kalshi" and series_ticker == "KXIPOANTHROPIC":
        return "A"
    if venue == "kalshi" and series_ticker == "KXANTHROPICLEADLEFT":
        return "B"
    if venue == "polymarket" and _B_TITLE.search(title):
        return "B"
    return None
