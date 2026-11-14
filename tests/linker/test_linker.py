from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from prooflag.linker.index import Company, TickerIndex
from prooflag.linker.normalize import normalize_name, normalize_ticker
from prooflag.linker.resolve import Alias, EntityLinker

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "sec"
ROWS = list(json.loads((FIX / "company_tickers_subset.json").read_text(encoding="utf-8")).values())
INDEX = TickerIndex.from_rows(ROWS)
ALIASES = [
    Alias(
        "MicroStrategy",
        "0001050446",
        "Strategy Inc",
        "former name of Strategy Inc; absent from company_tickers.json",
        "tests",
    ),
]
LINKER = EntityLinker(INDEX, ALIASES)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("NVIDIA CORP", "nvidia"),
        ("NVIDIA Corporation", "nvidia"),
        ("Tesla, Inc.", "tesla"),
        ("The Coca-Cola Company", "coca cola"),
        ("AT&T Inc.", "at and t"),
        ("  Rio   Tinto PLC ", "rio tinto"),
        ("Anthropic, PBC", "anthropic"),
        ("Strategy Inc", "strategy"),
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


def test_normalize_ticker_unifies_class_separators_and_case() -> None:
    assert normalize_ticker(" brk.b ") == normalize_ticker("BRK-B") == "BRK-B"
    assert normalize_ticker("nvda") == "NVDA"


def test_ticker_resolves_to_a_ten_digit_cik_with_method() -> None:
    for q in ("NVDA", " NVDA "):
        r = LINKER.resolve(q)
        assert (r.status, r.cik, r.method) == ("resolved", "0001045810", "ticker")


def test_share_classes_of_one_company_resolve_to_the_same_cik() -> None:
    a, b = LINKER.resolve("GOOG"), LINKER.resolve("GOOGL")
    assert a.status == b.status == "resolved" and a.cik == b.cik == "0001652044"


def test_exact_normalized_company_name_resolves() -> None:
    r = LINKER.resolve("NVIDIA Corporation")
    assert (r.status, r.cik, r.method) == ("resolved", "0001045810", "name")
    assert LINKER.resolve("Tesla, Inc.").cik == "0001318605"


def test_anthropic_resolves_from_the_sec_file() -> None:
    r = LINKER.resolve("Anthropic")
    assert r.status == "resolved" and r.cik == "0002130357"


def test_names_shared_by_two_companies_are_ambiguous_never_guessed() -> None:
    r = LINKER.resolve("Rio Tinto")
    assert r.status == "ambiguous" and r.cik is None
    assert {c.cik for c in r.candidates} == {"0000863064", "0000887028"}


def test_unknown_company_is_unresolved() -> None:
    r = LINKER.resolve("OpenAI")  # has no public EDGAR registration in the file
    assert r.status == "unresolved" and r.cik is None


def test_typos_produce_candidates_but_are_never_auto_accepted() -> None:
    r = LINKER.resolve("Nvidia Corporatoin")
    assert r.status == "unresolved" and r.cik is None and r.method == "fuzzy_candidates"
    assert any(c.cik == "0001045810" for c in r.candidates)


def test_reviewed_alias_resolves_a_former_name() -> None:
    r = LINKER.resolve("MicroStrategy")
    assert (r.status, r.cik, r.method) == ("resolved", "0001050446", "alias")
    assert LINKER.resolve("microstrategy inc").status == "resolved"  # normalized match


def test_empty_queries_are_unresolved() -> None:
    for q in ("", "   ", "...", "Inc."):
        r = LINKER.resolve(q)
        assert r.status == "unresolved" and r.cik is None


def test_ticker_and_name_pointing_at_different_companies_is_ambiguous() -> None:
    rows = [
        {"cik_str": 1, "ticker": "ACME", "title": "Widgets Holdings Inc"},
        {"cik_str": 2, "ticker": "AWI", "title": "Acme Corp"},
    ]
    r = EntityLinker(TickerIndex.from_rows(rows), []).resolve("ACME")
    assert r.status == "ambiguous" and {c.cik for c in r.candidates} == {"0000000001", "0000000002"}


def test_alias_conflicting_with_nothing_still_requires_reason_and_reviewer() -> None:
    with pytest.raises(ValueError):
        Alias("X", "0000000001", "X", "", "someone")
    with pytest.raises(ValueError):
        Alias("X", "0000000001", "X", "why", "")
    with pytest.raises(ValueError):
        Alias("X", "1234", "X", "why", "r")  # CIK must be 10 digits


@settings(max_examples=200, deadline=None)
@given(st.text(max_size=30))
def test_a_cik_is_returned_only_for_a_single_company(query: str) -> None:
    r = LINKER.resolve(query)
    if r.status == "resolved":
        assert r.cik is not None and len(r.cik) == 10 and r.cik.isdigit()
        if r.method != "alias":
            assert len({c.cik for c in r.candidates}) == 1
    else:
        assert r.cik is None
    assert r.status in ("resolved", "ambiguous", "unresolved")


def test_index_groups_tickers_by_company() -> None:
    comp = INDEX.by_cik("0001652044")
    assert isinstance(comp, Company) and set(comp.tickers) >= {"GOOG", "GOOGL"}
