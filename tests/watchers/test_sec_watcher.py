from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from prooflag.clock import FixedClock
from prooflag.ingest.cadence import Cadence
from prooflag.sec_client import SecClient
from prooflag.store.db import Db
from prooflag.store.locker import Locker
from prooflag.watchers.sec import CikWatchRepo, SecWatcher, WatchedCik, detection_lags
from prooflag.watchers.sec_service import SecService

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "sec"
ROOT = Path(__file__).resolve().parent.parent.parent
SUB = json.loads((FIX / "submissions_anthropic.json").read_text(encoding="utf-8"))
ATOM_8K = (FIX / "atom_getcurrent_8k.xml").read_text(encoding="utf-8")
CIK = "0002130357"
T0 = datetime(2026, 11, 14, 14, 59, 0, tzinfo=UTC)  # Saturday 09:59 ET (slow cadence)
WEEKDAY = datetime(2026, 11, 16, 15, 0, 0, tzinfo=UTC)  # Monday 10:00 ET (fast cadence)
WHY = "test"


class Sec:
    """A fake sec.gov: serves submissions JSON, Atom pages and archive documents."""

    def __init__(self) -> None:
        self.submissions: dict[str, dict[str, Any]] = {CIK: copy.deepcopy(SUB)}
        self.atom: dict[str, str] = {}
        self.docs: dict[str, bytes] = {}
        self.fail: int | None = None
        self.requests: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if self.fail is not None:
            return httpx.Response(self.fail)
        url = str(req.url)
        if "data.sec.gov/submissions/CIK" in url:
            cik = url.rsplit("CIK", 1)[1].split(".")[0]
            data = self.submissions.get(cik)
            return httpx.Response(200, json=data) if data else httpx.Response(404)
        if "browse-edgar" in url:
            form = dict(req.url.params).get("type", "")
            return httpx.Response(
                200, text=self.atom.get(form, "<feed xmlns='http://www.w3.org/2005/Atom'></feed>")
            )
        if url in self.docs:
            return httpx.Response(200, content=self.docs[url])
        return httpx.Response(404)

    def add_filing(self, cik: str, **row: Any) -> None:
        rec = self.submissions[cik]["filings"]["recent"]
        for k in rec:
            rec[k].insert(0, row.get(k, ""))


class Env:
    def __init__(self, tmp_path: Path, start: datetime = T0) -> None:
        self.sec = Sec()
        self.db = Db(tmp_path / "w.db")
        self.db.migrate()
        self.clock = FixedClock(start)
        self.sleeps: list[float] = []
        client = SecClient(
            user_agent="Prooflag t@example.org",
            max_rps=2.0,
            transport=httpx.MockTransport(self.sec),
            sleep=self.sleeps.append,
            clock=lambda: sum(self.sleeps),
        )
        self.client = client
        self.locker = Locker(tmp_path / "lk", self.db)
        self.watcher = SecWatcher(client, self.db, self.locker, self.clock)
        self.ciks = CikWatchRepo(self.db, self.clock)
        self.ciks.allow(WatchedCik(CIK, "Anthropic, PBC", "E2 subject", "tests"))
        self.svc = SecService(
            self.db,
            self.watcher,
            self.ciks,
            self.clock,
            cadence=Cadence("06:00", "22:00", 0.5, 15),
            atom_forms=("EFFECT", "424B4"),
        )

    def rows(self, sql: str, *a: Any) -> list[sqlite3.Row]:
        return self.db.conn.execute(sql, a).fetchall()


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    e = Env(tmp_path)
    yield e
    e.db.close()


NEW = {
    "accessionNumber": "0001628280-26-080001",
    "form": "EFFECT",
    "filingDate": "2026-11-16",
    "acceptanceDateTime": "2026-11-16T15:00:05.000Z",
    "primaryDocument": "",
    "items": "",
    "act": "",
    "fileNumber": "",
    "filmNumber": "",
    "size": 0,
    "isXBRL": 0,
    "isInlineXBRL": 0,
    "primaryDocDescription": "",
    "core_type": "",
}


def test_first_poll_is_a_baseline_and_emits_no_events(env: Env) -> None:
    got = env.watcher.poll_cik(CIK)
    assert got == []
    rows = env.rows("select * from filings where source='sec'")
    assert len(rows) == len(SUB["filings"]["recent"]["form"])
    assert all(r["detected_at_utc"] is None for r in rows)  # history is not a detection
    assert env.watcher.poll_cik(CIK) == []  # idempotent


def test_new_filing_is_detected_once_with_acceptance_and_detection_time_separate(env: Env) -> None:
    env.watcher.poll_cik(CIK)  # baseline
    env.sec.add_filing(CIK, **NEW)
    env.clock.advance(timedelta(hours=48, minutes=1, seconds=40))  # now 2026-11-16 15:00:40Z
    [ev] = env.watcher.poll_cik(CIK)
    assert ev.accession == "0001628280-26-080001" and ev.form == "EFFECT"
    assert ev.accepted_at_utc == datetime(2026, 11, 16, 15, 0, 5, tzinfo=UTC)
    assert ev.detected_at_utc == env.clock.now()
    assert ev.lag_seconds == pytest.approx(35.0 + 0.0)  # 15:00:40 minus 15:00:05
    row = env.rows("select * from filings where doc_id=?", ev.accession)[0]
    assert row["accepted_at_utc"] != row["detected_at_utc"]
    assert row["posted_kind"] == "accepted" and row["discovered_via"] == "submissions"
    assert env.watcher.poll_cik(CIK) == []  # not re-emitted
    lags = detection_lags(env.db)
    assert lags.n == 1 and lags.median_seconds == pytest.approx(35.0)


def test_poll_log_records_health_for_each_poll(env: Env) -> None:
    env.watcher.poll_cik(CIK)
    r = env.rows("select * from poll_log where source=?", f"sec:submissions:{CIK}")
    assert (
        len(r) == 1 and r[0]["ok"] == 1 and r[0]["items"] == len(SUB["filings"]["recent"]["form"])
    )


def test_atom_discovery_comes_first_and_submissions_later_confirms_without_a_new_event(
    env: Env,
) -> None:
    # Watch MacroGenics too; baseline it from an empty submissions page, then the Atom feed shows
    # a filing before the submissions JSON has it.
    mg = "0001125345"
    env.ciks.allow(WatchedCik(mg, "MacroGenics", "atom test", "tests"))
    empty = copy.deepcopy(SUB)
    empty["cik"] = int(mg)
    for k in empty["filings"]["recent"]:
        empty["filings"]["recent"][k] = []
    env.sec.submissions[mg] = empty
    env.watcher.poll_cik(mg)  # baseline (nothing yet)
    env.sec.atom["8-K"] = ATOM_8K
    [ev] = [e for e in env.watcher.poll_atom("8-K")]  # one entry belongs to the watched CIK
    assert ev.cik == mg and ev.discovered_via == "atom" and ev.accepted_at_utc is None
    row = env.rows("select * from filings where doc_id=?", ev.accession)[0]
    assert row["accepted_at_utc"] is None and row["detected_at_utc"] is not None
    detected_first = row["detected_at_utc"]
    # later the submissions JSON catches up and fills the authoritative acceptance time
    env.clock.advance(timedelta(minutes=3))
    env.sec.add_filing(
        mg,
        accessionNumber=ev.accession,
        form="8-K",
        filingDate="2026-11-13",
        acceptanceDateTime="2026-11-13T22:28:30.000Z",
        primaryDocument="d8k.htm",
        items="7.01,9.01",
    )
    assert env.watcher.poll_cik(mg) == []  # same filing: no second event
    row = env.rows("select * from filings where doc_id=?", ev.accession)[0]
    assert row["accepted_at_utc"] == "2026-11-13T22:28:30+00:00"
    assert row["detected_at_utc"] == detected_first and row["discovered_via"] == "atom"
    assert row["primary_document"] == "d8k.htm" and row["items"] == "7.01,9.01"


def test_atom_ignores_unwatched_ciks_and_unbaselined_watched_ones(env: Env) -> None:
    env.sec.atom["8-K"] = ATOM_8K
    assert env.watcher.poll_atom("8-K") == []  # MacroGenics etc. are not on the watch list
    mg = "0001125345"
    env.ciks.allow(WatchedCik(mg, "MacroGenics", "atom test", "tests"))
    assert env.watcher.poll_atom("8-K") == []  # watched but never baselined: history is not "new"


def test_primary_document_is_stored_in_the_locker_with_acceptance_time(env: Env) -> None:
    cik = "0001050446"
    body = (ROOT / "fixtures" / "strategy_2026_05" / "8k_20260601_mstr-20260530.htm").read_bytes()
    sub = copy.deepcopy(SUB)
    sub["cik"], sub["name"] = int(cik), "Strategy Inc"
    for k in sub["filings"]["recent"]:
        sub["filings"]["recent"][k] = []
    env.sec.submissions[cik] = sub
    env.ciks.allow(WatchedCik(cik, "Strategy Inc", "fixture", "tests"))
    env.watcher.poll_cik(cik)  # baseline
    env.sec.add_filing(
        cik,
        accessionNumber="0001193125-26-249768",
        form="8-K",
        filingDate="2026-06-01",
        acceptanceDateTime="2026-06-01T12:00:16.000Z",
        primaryDocument="mstr-20260530.htm",
        items="7.01,8.01",
    )
    url = "https://www.sec.gov/Archives/edgar/data/1050446/000119312526249768/mstr-20260530.htm"
    env.sec.docs[url] = body
    [ev] = env.watcher.poll_cik(cik)
    sha = env.watcher.fetch_primary(ev.accession)
    assert sha == hashlib.sha256(body).hexdigest()
    art = env.rows("select * from artifacts where sha256=?", sha)[0]
    assert art["kind"] == "sec_primary_doc" and art["source_url"] == url
    assert art["accepted_at_utc"] == "2026-06-01T12:00:16+00:00"  # acceptance, not fetch time
    assert art["fetched_at_utc"] == env.clock.now().isoformat()
    assert env.rows("select primary_doc_sha from filings where doc_id=?", ev.accession)[0][0] == sha
    n = len(env.sec.requests)
    assert env.watcher.fetch_primary(ev.accession) == sha and len(env.sec.requests) == n  # cached


def test_filings_without_a_primary_document_or_a_404_are_handled(env: Env) -> None:
    env.watcher.poll_cik(CIK)
    env.sec.add_filing(CIK, **NEW)
    env.clock.advance(timedelta(days=2))
    [ev] = env.watcher.poll_cik(CIK)
    assert env.watcher.fetch_primary(ev.accession) is None  # EFFECT notices have no document
    row = env.rows("select * from filings where doc_id=?", "0001628280-26-067168")[0]
    assert env.watcher.fetch_primary(row["doc_id"]) is None  # 404 on the archive: no crash


def test_a_filing_shared_by_two_watched_ciks_is_stored_once_and_emitted_once(env: Env) -> None:
    # Co-registrants (e.g. an issuer and a reporting owner) list the SAME accession in both
    # submissions files; the second CIK must not crash on the unique key or emit a duplicate.
    other = "0001050446"
    env.ciks.allow(WatchedCik(other, "Co-registrant", "test", "tests"))
    twin = copy.deepcopy(SUB)
    twin["cik"] = int(other)
    env.sec.submissions[other] = twin
    env.watcher.poll_cik(CIK)
    env.watcher.poll_cik(other)  # baseline of the second CIK: same accessions, no crash
    shared = copy.deepcopy(NEW)
    env.sec.add_filing(CIK, **shared)
    env.sec.add_filing(other, **shared)
    env.clock.advance(timedelta(days=2))
    first = env.watcher.poll_cik(CIK)
    second = env.watcher.poll_cik(other)
    assert [f.accession for f in first] == ["0001628280-26-080001"] and second == []
    n = env.rows("select count(*) from filings where doc_id='0001628280-26-080001'")[0][0]
    assert n == 1


def test_requests_stay_under_two_per_second(env: Env) -> None:
    for i in range(8):
        sub = copy.deepcopy(SUB)
        rec = sub["filings"]["recent"]
        rec["accessionNumber"] = [f"{a}-{i}" for a in rec["accessionNumber"]]
        env.sec.submissions[f"{i:010d}"] = sub
        env.watcher.poll_cik(f"{i:010d}")
    assert sum(env.sleeps) >= 7 * 0.5 - 1e-9  # 8 requests at 2 req/s


# -- service: cadence, backoff, resilience ------------------------------------------------------
def test_fast_cadence_in_the_edgar_window_and_slow_outside(tmp_path: Path) -> None:
    e = Env(tmp_path, start=WEEKDAY)
    try:
        r1 = e.svc.run_due()
        assert r1.polled_ciks == 1 and r1.polled_atom == 2
        e.clock.advance(timedelta(seconds=29))
        assert e.svc.run_due().polled_ciks == 0  # inside the 30 s interval
        e.clock.advance(timedelta(seconds=1))
        assert e.svc.run_due().polled_ciks == 1  # 30 s: due again
        sat = Env(tmp_path / "x", start=T0)  # Saturday: 15-minute cadence
        sat.svc.run_due()
        sat.clock.advance(timedelta(minutes=14, seconds=59))
        assert sat.svc.run_due().polled_ciks == 0
        sat.clock.advance(timedelta(seconds=1))
        assert sat.svc.run_due().polled_ciks == 1
        sat.db.close()
    finally:
        e.db.close()


def test_failures_back_off_and_run_due_never_raises(env: Env) -> None:
    env.sec.fail = 403  # SEC refuses: e.g. missing contact in the User-Agent
    attempts = []
    for _ in range(10):
        env.svc.run_due()
        attempts.append(len(env.sec.requests))
        env.clock.advance(timedelta(minutes=1))
    assert len(env.sec.requests) <= 12  # not 10 minutes x 3 sources every tick
    err = env.rows("select * from poll_log where ok=0 and source like 'sec:%'")
    assert err and "403" in (err[0]["err"] or "")


def test_new_filing_flows_through_the_service_with_primary_fetch(tmp_path: Path) -> None:
    e = Env(tmp_path, start=WEEKDAY)
    try:
        e.svc.run_due()  # baseline
        e.sec.add_filing(
            CIK,
            **{
                **NEW,
                "form": "424B4",
                "primaryDocument": "p.htm",
                "accessionNumber": "0001628280-26-080002",
            },
        )
        e.sec.docs["https://www.sec.gov/Archives/edgar/data/2130357/000162828026080002/p.htm"] = (
            b"<html>x</html>"
        )
        e.clock.advance(timedelta(seconds=40))
        r = e.svc.run_due()
        assert [f.form for f in r.new_filings] == ["424B4"]
        assert e.rows("select primary_doc_sha from filings where doc_id='0001628280-26-080002'")[0][
            0
        ]
    finally:
        e.db.close()


# -- watch list ---------------------------------------------------------------------------------
def test_cik_watch_list_is_append_only_with_reason_and_reviewer(env: Env) -> None:
    repo = env.ciks
    w = WatchedCik("0001050446", "Strategy Inc", "Strategy fixture", "tests")
    assert repo.allow(w) and not repo.allow(w)
    assert {c.cik for c in repo.snapshot()} == {CIK, "0001050446"}
    assert repo.revoke(w)
    assert {c.cik for c in repo.snapshot()} == {CIK}
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        env.db.conn.execute("update watch_ciks set reason='x'")
    with pytest.raises(ValueError):
        repo.allow(WatchedCik("123", "bad cik", "r", "t"))
    with pytest.raises(ValueError):
        repo.allow(WatchedCik("0001050446", "x", " ", "t"))


def test_watch_ciks_seed_file(env: Env) -> None:
    seed = ROOT / "config" / "watch_ciks.json"
    n = env.ciks.seed_from_file(seed)
    assert n >= 1 and env.ciks.seed_from_file(seed) == 0
    got = {c.cik for c in env.ciks.snapshot()}
    assert {"0002130357", "0001050446"} <= got
    assert "@" not in seed.read_text(encoding="utf-8")
