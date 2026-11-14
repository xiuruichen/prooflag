from __future__ import annotations

from test_linker import LINKER

from prooflag.linker.index import TickerIndex
from prooflag.linker.resolve import EntityLinker

FORD_ROWS = [
    {"cik_str": 38264, "ticker": "F", "title": "FORD MOTOR CO"},
    {"cik_str": 38264, "ticker": "F-PB", "title": "FORD MOTOR CO"},
    {"cik_str": 1000, "ticker": "FORD", "title": "FORWARD INDUSTRIES INC"},
    {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    {"cik_str": 2000, "ticker": "APLE", "title": "Apple Hospitality REIT, Inc."},
]


def test_a_common_word_that_is_someone_elses_ticker_is_not_auto_resolved() -> None:
    linker = EntityLinker(TickerIndex.from_rows(FORD_ROWS), [])
    for q in ("Ford", "ford"):
        r = linker.resolve(q)
        assert r.status == "ambiguous" and r.cik is None  # FORD is Forward Industries
    assert linker.resolve("FORD").cik == "0000001000"  # written as a ticker: trusted
    assert linker.resolve("Apple Inc.").cik == "0000320193"  # exact name wins over a lookalike
    assert linker.resolve("Ford Motor Company").cik == "0000038264"


def test_single_letter_queries_are_never_auto_resolved() -> None:
    linker = EntityLinker(TickerIndex.from_rows(FORD_ROWS), [])
    r = linker.resolve("F")
    assert r.status == "ambiguous" and r.cik is None and r.method == "short_ticker"
    assert [c.cik for c in r.candidates] == ["0000038264"]


def test_lowercase_ticker_like_queries_go_to_review() -> None:
    r = LINKER.resolve("nvda")
    assert r.status == "ambiguous" and r.cik is None
    assert [c.cik for c in r.candidates] == ["0001045810"]
