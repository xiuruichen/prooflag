"""Weekly executive-order markets: rule parsing and the deciding-document logic (E1)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
Basis = Literal["pi", "pub"]

_DATE = r"([A-Z][a-z]{2} \d{1,2}, \d{4})"
_RULE_RE = re.compile(
    r"signs (?P<kind>above|any|at least|exactly)(?: (?P<n>\d+))?"
    r" (?:executive orders?|Executive Orders?)"
    rf" (?:during|between|from) {_DATE} to {_DATE}",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EoDoc:
    """One executive order as recorded in the Federal Register."""

    number: int | None
    doc_number: str
    signing_date: date
    publication_date: date
    pi_filed_at: datetime | None  # public-inspection posting time (tz-aware), if known

    @property
    def t_pub(self) -> datetime:
        """Official publication, ASSUMED to be 06:00 ET on the publication date (the daily issue
        goes online that morning; the exact time is not published)."""
        return datetime.combine(self.publication_date, time(6, 0), ET)

    def posting_time(self, basis: Basis) -> datetime | None:
        return self.pi_filed_at if basis == "pi" else self.t_pub


@dataclass(frozen=True)
class Rule:
    kind: str  # above | any | at_least | exactly
    n: int
    start: date
    end: date

    @property
    def needed(self) -> int | None:
        """How many in-window EOs make the market Yes; None for 'exactly' (not first-crossing)."""
        return {"above": self.n + 1, "any": 1, "at_least": self.n}.get(self.kind)


def _d(s: str) -> date:
    return datetime.strptime(s, "%b %d, %Y").date()


def parse_rule(text: str) -> Rule | None:
    m = _RULE_RE.search(text or "")
    if not m:
        return None
    kind = m.group("kind").lower().replace(" ", "_")
    n = int(m.group("n")) if m.group("n") else 0
    return Rule(kind, n, _d(m.group(3)), _d(m.group(4)))


def dedupe(eos: list[EoDoc]) -> list[EoDoc]:
    """One document per executive-order number (a reissue repeats the number); keep the earliest
    posting. Documents without a number are kept by document number."""
    best: dict[object, EoDoc] = {}
    for e in eos:
        key: object = e.number if e.number is not None else e.doc_number
        cur = best.get(key)
        if cur is None or (e.publication_date, e.doc_number) < (
            cur.publication_date,
            cur.doc_number,
        ):
            best[key] = e
    return sorted(best.values(), key=lambda e: (e.signing_date, e.number or 0, e.doc_number))


def in_window(eos: list[EoDoc], start: date, end: date) -> list[EoDoc]:
    """EOs whose FR signing date lies in [start, end] (inclusive)."""
    return [e for e in eos if start <= e.signing_date <= end]


def implied_result(rule: Rule, count: int) -> str:
    if rule.kind == "exactly":
        return "yes" if count == rule.n else "no"
    needed = rule.needed
    assert needed is not None
    return "yes" if count >= needed else "no"


def deciding_eo(rule: Rule, in_window_eos: list[EoDoc], basis: Basis) -> EoDoc | None:
    """The EO whose posting makes the market provably Yes: the needed-th smallest posting time
    among the in-window EOs (NOT the needed-th by signing date). None if never provable or the
    rule is 'exactly'. EOs with no posting time for ``basis`` are excluded."""
    needed = rule.needed
    if needed is None:
        return None
    timed = [(e.posting_time(basis), e) for e in in_window_eos]
    ordered = sorted(
        ((t, e.number or 0, e.doc_number, e) for t, e in timed if t is not None),
        key=lambda x: (x[0], x[1], x[2]),
    )
    if len(ordered) < needed:
        return None
    return ordered[needed - 1][3]
