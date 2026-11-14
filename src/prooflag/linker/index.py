"""In-memory index over the SEC company_tickers.json rows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from prooflag.linker.normalize import normalize_name, normalize_ticker


def pad_cik(cik: int | str) -> str:
    return f"{int(cik):010d}"


@dataclass(frozen=True)
class Company:
    cik: str  # 10 digits, zero padded
    name: str
    tickers: tuple[str, ...]


def _prefix_score(a: str, b: str) -> float:
    """0.9 when one normalized name is a whole-word prefix of the other (catches typos in a trailing
    legal suffix, e.g. 'nvidia corporatoin' vs 'nvidia'); candidate-only, never an auto-match."""
    ta, tb = a.split(), b.split()
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if short and long_[: len(short)] == short and len(" ".join(short)) >= 4:
        return 0.9
    return 0.0


class TickerIndex:
    def __init__(self, companies: dict[str, Company]) -> None:
        self._by_cik = companies
        self._by_ticker: dict[str, set[str]] = defaultdict(set)
        self._by_name: dict[str, set[str]] = defaultdict(set)
        for c in companies.values():
            for t in c.tickers:
                self._by_ticker[normalize_ticker(t)].add(c.cik)
            norm = normalize_name(c.name)
            if norm:
                self._by_name[norm].add(c.cik)

    @classmethod
    def from_rows(cls, rows: Iterable[dict[str, Any]]) -> TickerIndex:
        tickers: dict[str, list[str]] = defaultdict(list)
        names: dict[str, str] = {}
        for r in rows:
            cik = pad_cik(r["cik_str"])
            tickers[cik].append(str(r["ticker"]))
            names.setdefault(cik, str(r["title"]))
        return cls({c: Company(c, names[c], tuple(tickers[c])) for c in names})

    def by_cik(self, cik: str) -> Company | None:
        return self._by_cik.get(cik)

    def by_ticker(self, ticker: str) -> list[Company]:
        return [self._by_cik[c] for c in sorted(self._by_ticker.get(normalize_ticker(ticker), ()))]

    def by_name(self, normalized: str) -> list[Company]:
        return [self._by_cik[c] for c in sorted(self._by_name.get(normalized, ()))]

    def fuzzy(self, normalized: str, *, limit: int = 5, cutoff: float = 0.84) -> list[Company]:
        """Near matches by normalized-name similarity. These are CANDIDATES for review only."""
        if not normalized:
            return []
        scored: list[tuple[float, str]] = []
        for norm, ciks in self._by_name.items():
            ratio = max(
                SequenceMatcher(None, normalized, norm).ratio(), _prefix_score(normalized, norm)
            )
            if ratio >= cutoff:
                scored.extend((ratio, c) for c in ciks)
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [self._by_cik[c] for _, c in scored[:limit]]
