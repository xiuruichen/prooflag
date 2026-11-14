"""Regressions from the S3/S4 checker review (SEC watcher)."""

from __future__ import annotations

import copy
import sqlite3
from datetime import timedelta
from typing import Any

import pytest
from test_sec_watcher import CIK, NEW, SUB, WEEKDAY, Env

from prooflag.watchers.sec_parse import parse_atom


def test_missed_primary_documents_are_retried_on_later_ticks(tmp_path) -> None:  # type: ignore[no-untyped-def]
    e = Env(tmp_path, start=WEEKDAY)
    try:
        e.svc.run_due()  # baseline
        acc = "0001628280-26-080003"
        e.sec.add_filing(
            CIK, **{**NEW, "form": "424B4", "primaryDocument": "p.htm", "accessionNumber": acc}
        )
        url = "https://www.sec.gov/Archives/edgar/data/2130357/000162828026080003/p.htm"
        e.clock.advance(timedelta(seconds=40))
        e.svc.run_due()  # event tick: the document is not on the archive yet (404)
        assert e.rows("select primary_doc_sha from filings where doc_id=?", acc)[0][0] is None
        e.sec.docs[url] = b"<html>now there</html>"
        for _ in range(8):  # later ticks pick it up, though no new event fires
            e.clock.advance(timedelta(minutes=3))
            e.svc.run_due()
        assert e.rows("select primary_doc_sha from filings where doc_id=?", acc)[0][0] is not None
    finally:
        e.db.close()


def test_history_from_the_baseline_is_never_bulk_downloaded(tmp_path) -> None:  # type: ignore[no-untyped-def]
    e = Env(tmp_path, start=WEEKDAY)
    try:
        e.svc.run_due()
        for _ in range(3):
            e.clock.advance(timedelta(minutes=2))
            e.svc.run_due()
        assert not [r for r in e.sec.requests if "/Archives/edgar/data/" in str(r.url)]
    finally:
        e.db.close()


def test_a_baseline_where_no_row_parses_is_not_a_baseline(tmp_path) -> None:  # type: ignore[no-untyped-def]
    e = Env(tmp_path)
    try:
        bad = copy.deepcopy(SUB)
        n = len(bad["filings"]["recent"]["form"])
        bad["filings"]["recent"]["acceptanceDateTime"] = ["garbage"] * n
        e.sec.submissions[CIK] = bad
        with pytest.raises(ValueError, match="parse"):
            e.watcher.poll_cik(CIK)
        e.sec.submissions[CIK] = copy.deepcopy(SUB)
        assert e.watcher.poll_cik(CIK) == []  # the first GOOD poll is the baseline
        assert e.rows("select count(*) from filings where detected_at_utc is not null")[0][0] == 0
    finally:
        e.db.close()


def test_the_ok_log_row_is_written_in_the_same_transaction_as_the_filings(
    tmp_path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    import prooflag.watchers.sec as sec_mod

    e = Env(tmp_path)
    try:
        real = sec_mod.log_poll

        def boom(*a: Any, **kw: Any) -> None:
            if kw.get("ok"):
                raise sqlite3.OperationalError("disk full")
            real(*a, **kw)

        monkeypatch.setattr(sec_mod, "log_poll", boom)
        with pytest.raises(sqlite3.OperationalError):
            e.watcher.poll_cik(CIK)
        monkeypatch.setattr(sec_mod, "log_poll", real)
        # nothing was committed, so the retry is still a baseline: no swallowed real filing
        assert e.rows("select count(*) from filings")[0][0] == 0
        assert e.watcher.poll_cik(CIK) == []
    finally:
        e.db.close()


def test_fast_cadence_failures_still_back_off(tmp_path) -> None:  # type: ignore[no-untyped-def]
    e = Env(tmp_path, start=WEEKDAY)  # 30 s fast cadence
    try:
        e.sec.fail = 503
        for _ in range(60):  # one hour of 30 s ticks
            e.svc.run_due()
            e.clock.advance(timedelta(seconds=30))
        # grows toward a 15 minute interval instead of 3 sources every 30 s (= 360 attempts)
        assert len(e.sec.requests) <= 3 * 5 * 10
    finally:
        e.db.close()


def test_atom_entry_without_a_real_accession_number_is_skipped() -> None:
    from test_sec_watcher import ATOM_8K

    bad = ATOM_8K.replace(
        "urn:tag:sec.gov,2008:accession-number=0001125345-26-000077",
        "urn:tag:sec.gov,2008:other",
        1,
    )
    assert len(parse_atom(bad)) == 9
