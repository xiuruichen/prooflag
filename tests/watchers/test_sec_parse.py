from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from prooflag.watchers.sec_parse import parse_atom, parse_submissions

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "sec"
SUB = json.loads((FIX / "submissions_anthropic.json").read_text(encoding="utf-8"))
ATOM = (FIX / "atom_getcurrent_8k.xml").read_text(encoding="utf-8")


def by_acc(rows, acc):  # type: ignore[no-untyped-def]
    return next(r for r in rows if r.accession == acc)


def test_parse_submissions_reads_every_recent_filing_with_padded_cik() -> None:
    rows = parse_submissions(SUB)
    assert len(rows) == len(SUB["filings"]["recent"]["form"])
    assert all(r.cik == "0002130357" for r in rows)
    forms = {r.form for r in rows}
    assert {"S-1", "S-1/A", "FWP", "DRS", "DRS/A"} <= forms


def test_acceptance_time_is_utc_and_kept_separate_from_the_filing_date() -> None:
    rows = parse_submissions(SUB)
    s1 = by_acc(rows, "0001628280-26-067168")  # the public S-1
    assert s1.form == "S-1"
    assert s1.accepted_at_utc == datetime(2026, 10, 26, 13, 0, 11, tzinfo=UTC)
    assert s1.filed_date.isoformat() == "2026-10-26"
    assert s1.date_basis_differs is False  # accepted 09:00 ET the same day


def test_filing_dated_after_the_acceptance_day_is_flagged() -> None:
    # Real case: FWP accepted 2026-11-11T01:35:49Z (= 20:35 ET on Nov 10) but dated Nov 12.
    rows = parse_submissions(SUB)
    fwp = by_acc(rows, "0001628280-26-072949")
    assert fwp.accepted_at_utc == datetime(2026, 11, 11, 1, 35, 49, tzinfo=UTC)
    assert fwp.filed_date.isoformat() == "2026-11-12"
    assert fwp.date_basis_differs is True


def test_urls_are_built_from_the_cik_and_accession() -> None:
    s1 = by_acc(parse_submissions(SUB), "0001628280-26-067168")
    base = "https://www.sec.gov/Archives/edgar/data/2130357/000162828026067168/"
    assert s1.index_url == base + "0001628280-26-067168-index.htm"
    assert s1.primary_url is not None and s1.primary_url.startswith(base)
    assert s1.primary_url.endswith(s1.primary_document)


def test_a_filing_without_a_primary_document_has_no_primary_url() -> None:
    sub = json.loads(json.dumps(SUB))
    sub["filings"]["recent"]["primaryDocument"][0] = ""
    assert parse_submissions(sub)[0].primary_url is None


def test_malformed_rows_are_skipped_not_fatal() -> None:
    sub = json.loads(json.dumps(SUB))
    sub["filings"]["recent"]["acceptanceDateTime"][1] = "garbage"
    rows = parse_submissions(sub)
    assert len(rows) == len(SUB["filings"]["recent"]["form"]) - 1


def test_parse_atom_entries() -> None:
    entries = parse_atom(ATOM)
    assert len(entries) == 10
    e = entries[0]
    assert e.form == "8-K" and e.cik == "0001125345" and e.accession == "0001125345-26-000077"
    assert e.filed_date.isoformat() == "2026-11-13"
    assert e.updated.tzinfo is not None and e.updated.astimezone(UTC).hour == 22
    assert e.index_url.endswith("0001125345-26-000077-index.htm")
    assert e.company == "MACROGENICS INC"


def test_parse_atom_tolerates_garbage_and_empty_input() -> None:
    assert parse_atom("") == []
    assert parse_atom("<feed></feed>") == []
    with pytest.raises(ValueError):
        parse_atom("not xml at all <<<")
