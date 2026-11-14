from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from prooflag.compiler.extract import extract_deadline, extract_forms, normalize_text, verify_span


def test_et_deadline_in_rules_with_date_in_title_uses_eastern_time() -> None:
    d = extract_deadline(
        "Will X sell by May 31, 2026?",
        "Resolves Yes if X sells by 11:59 PM ET on the date specified in the title.",
    )
    assert d.utc == datetime(2026, 6, 1, 3, 59, tzinfo=UTC)  # EDT = UTC-4
    assert d.tz_original == "ET" and d.status == "ok"
    assert d.span == "11:59 PM ET"


def test_winter_date_uses_est_offset() -> None:
    d = extract_deadline("t", "Resolves Yes if filed by 11:59 PM ET on January 15, 2027.")
    assert d.utc == datetime(2027, 1, 16, 4, 59, tzinfo=UTC)


def test_naive_time_is_ambiguous_never_assumed() -> None:
    d = extract_deadline("t", "Resolves Yes if filed by 11:59 PM on January 15, 2027.")
    assert d.utc is None and d.status == "naive_timezone"


def test_date_only_has_no_time_and_is_ambiguous() -> None:
    d = extract_deadline("t", "Resolves Yes if filed on or before January 15, 2027.")
    assert d.utc is None and d.status == "date_only"


def test_end_of_day_is_not_resolved() -> None:
    d = extract_deadline("t", "Resolves Yes if filed by end of day January 15, 2027 ET.")
    assert d.utc is None and d.status in {"date_only", "vague_time"}


def test_no_deadline_found() -> None:
    assert extract_deadline("t", "Resolves based on the filing.").status == "none"


def test_dst_spring_forward_day_uses_the_correct_offset() -> None:
    d = extract_deadline("t", "by 11:59 PM ET on March 14, 2027")
    assert d.utc == datetime(2027, 3, 15, 3, 59, tzinfo=UTC)


def test_forms_lexicon() -> None:
    assert extract_forms("an 8-K or a Form 10-Q, also S-1/A and Form 4") == [
        "8-K",
        "10-Q",
        "S-1/A",
        "4",
    ]
    assert extract_forms("no forms here") == []


def test_verify_span_is_verbatim_after_canonical_whitespace_and_quotes() -> None:
    corpus = "Resolves  “Yes”\nif X sells by 11:59 PM ET."
    assert verify_span('Resolves "Yes" if X sells', corpus)
    assert verify_span("by 11:59 PM ET.", corpus)
    assert not verify_span("Resolves Yes if X sells", corpus)
    assert not verify_span("", corpus)
    assert not verify_span("X sold bitcoin", corpus)


_ASCII = st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126))


@given(_ASCII.filter(bool), _ASCII, _ASCII)
def test_any_substring_of_the_corpus_verifies(core: str, pre: str, post: str) -> None:
    if not normalize_text(core):
        return
    assert verify_span(core, pre + core + post)


@pytest.mark.parametrize("bad", ["", "   "])
def test_blank_spans_never_verify(bad: str) -> None:
    assert not verify_span(bad, "anything")
