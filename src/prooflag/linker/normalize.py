"""Deterministic normalization of company names and tickers."""

from __future__ import annotations

import re

_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited",
    "plc", "llc", "lp", "pbc", "sa", "nv", "ag",
}  # fmt: skip
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")


def normalize_name(name: str) -> str:
    """Lower-case, '&' -> 'and', punctuation to spaces, drop a leading 'the' and trailing legal
    suffixes (Inc, Corp, PLC, PBC ...). 'Holdings' / 'Group' are kept: they tell companies apart."""
    n = _NON_ALNUM.sub(" ", name.lower().replace("&", " and "))
    toks = n.split()
    while toks and toks[-1] in _SUFFIXES:
        toks.pop()
    if toks and toks[0] == "the":
        toks = toks[1:]
    return " ".join(toks)


def normalize_ticker(ticker: str) -> str:
    """Upper-case, whitespace stripped, class separators ('.', '/', '_') unified to '-'."""
    return re.sub(r"[./_]", "-", ticker.strip().upper())
