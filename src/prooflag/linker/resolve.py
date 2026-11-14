"""Resolve a company name or ticker to a CIK. Never guesses: a CIK is returned only when exactly one
company matches (or a reviewed alias says so); everything else is flagged for review."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from prooflag.linker.index import Company, TickerIndex
from prooflag.linker.normalize import normalize_name, normalize_ticker

_TICKER_LIKE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,5}([./-][A-Za-z0-9]{1,3})?$")


@dataclass(frozen=True)
class Alias:
    """A reviewed mapping (e.g. a former name) that overrides the SEC file."""

    alias: str
    cik: str
    name: str
    reason: str
    reviewer: str

    def __post_init__(self) -> None:
        if not self.reason.strip() or not self.reviewer.strip():
            raise ValueError("aliases need a reason and a reviewer")
        if not (len(self.cik) == 10 and self.cik.isdigit()):
            raise ValueError("alias CIK must be 10 digits")


@dataclass
class LinkResult:
    query: str
    status: str  # resolved | ambiguous | unresolved
    cik: str | None
    method: str  # alias | ticker | name | fuzzy_candidates | none | empty
    candidates: list[Company] = field(default_factory=list)


class EntityLinker:
    def __init__(self, index: TickerIndex, aliases: Iterable[Alias] = ()) -> None:
        self._index = index
        self._aliases = {normalize_name(a.alias): a for a in aliases}

    def resolve(self, query: str) -> LinkResult:
        name_key = normalize_name(query)
        if not query.strip() or (not name_key and not _TICKER_LIKE.match(query.strip())):
            return LinkResult(query, "unresolved", None, "empty")
        alias = self._aliases.get(name_key)
        if alias is not None:
            return LinkResult(
                query, "resolved", alias.cik, "alias", [Company(alias.cik, alias.name, ())]
            )
        by_ticker = (
            self._index.by_ticker(normalize_ticker(query))
            if _TICKER_LIKE.match(query.strip())
            else []
        )
        by_name = self._index.by_name(name_key) if name_key else []
        merged: dict[str, Company] = {c.cik: c for c in [*by_ticker, *by_name]}
        stripped = query.strip()
        if by_ticker and not by_name:
            # A ticker hit is trusted only when the query is WRITTEN as a ticker (upper case) and is
            # not a single letter: "Ford" is a name that happens to be someone else's ticker.
            if len(normalize_ticker(query)) == 1:
                return LinkResult(query, "ambiguous", None, "short_ticker", by_ticker)
            if stripped != stripped.upper():
                return LinkResult(query, "ambiguous", None, "ticker_case_mismatch", by_ticker)
        if len(merged) == 1:
            method = "ticker" if by_ticker else "name"
            (only,) = merged.values()
            return LinkResult(query, "resolved", only.cik, method, [only])
        if len(merged) > 1:
            cands = sorted(merged.values(), key=lambda c: c.cik)
            return LinkResult(
                query,
                "ambiguous",
                None,
                "ticker+name" if by_ticker and by_name else ("ticker" if by_ticker else "name"),
                cands,
            )
        fuzzy = self._index.fuzzy(name_key)
        if fuzzy:
            return LinkResult(query, "unresolved", None, "fuzzy_candidates", fuzzy)
        return LinkResult(query, "unresolved", None, "none")
