"""SEC EDGAR watcher: authoritative acceptance times from submissions JSON, discovery via Atom."""

from __future__ import annotations

import json
import logging
import statistics
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from prooflag.clock import Clock
from prooflag.scheduling import has_ok_poll, log_poll
from prooflag.sec_client import SecClient, SecHTTPError
from prooflag.store.db import Db
from prooflag.store.locker import Locker
from prooflag.watchers.sec_parse import ARCHIVES, parse_atom, parse_submissions

log = logging.getLogger(__name__)
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
ATOM = "https://www.sec.gov/cgi-bin/browse-edgar"
MAX_DOC_BYTES = 25_000_000


def _validate_cik(cik: str) -> None:
    if not (len(cik) == 10 and cik.isdigit()):
        raise ValueError(f"CIK must be 10 digits: {cik!r}")


@dataclass(frozen=True)
class WatchedCik:
    cik: str
    name: str
    reason: str
    reviewer: str

    def __post_init__(self) -> None:
        _validate_cik(self.cik)
        if not self.reason.strip() or not self.reviewer.strip():
            raise ValueError("watch entries need a reason and a reviewer")


@dataclass(frozen=True)
class NewFiling:
    cik: str
    accession: str
    form: str
    filed_date: date
    accepted_at_utc: datetime | None  # None when first seen via Atom (not yet in submissions)
    detected_at_utc: datetime
    discovered_via: str
    url: str

    @property
    def lag_seconds(self) -> float | None:
        if self.accepted_at_utc is None:
            return None
        return (self.detected_at_utc - self.accepted_at_utc).total_seconds()


@dataclass(frozen=True)
class Lags:
    n: int
    median_seconds: float | None
    max_seconds: float | None


def detection_lags(db: Db) -> Lags:
    """Detection lag = our detection time minus EDGAR's acceptance time, for detected filings."""
    rows = db.conn.execute(
        "select accepted_at_utc, detected_at_utc from filings where source='sec'"
        " and accepted_at_utc is not null and detected_at_utc is not null"
    ).fetchall()
    lags = [
        (datetime.fromisoformat(r[1]) - datetime.fromisoformat(r[0])).total_seconds() for r in rows
    ]
    if not lags:
        return Lags(0, None, None)
    return Lags(len(lags), statistics.median(lags), max(lags))


class CikWatchRepo:
    def __init__(self, db: Db, clock: Clock) -> None:
        self.db = db
        self.clock = clock

    def _latest(self, cik: str) -> str | None:
        row = self.db.conn.execute(
            "select action from watch_ciks where cik=? order by entry_id desc limit 1", (cik,)
        ).fetchone()
        return None if row is None else str(row[0])

    def _append(self, action: str, w: WatchedCik, source: str | None) -> bool:
        if self._latest(w.cik) == action:
            return False
        self.db.conn.execute(
            "insert into watch_ciks(action, cik, name, reason, reviewer, added_at, source)"
            " values (?,?,?,?,?,?,?)",
            (action, w.cik, w.name, w.reason, w.reviewer, self.clock.now().isoformat(), source),
        )
        return True

    def allow(self, w: WatchedCik, source: str | None = None) -> bool:
        return self._append("allow", w, source)

    def revoke(self, w: WatchedCik, source: str | None = None) -> bool:
        return self._append("revoke", w, source)

    def snapshot(self) -> list[WatchedCik]:
        rows = self.db.conn.execute(
            "select a.cik, a.name, a.reason, a.reviewer, a.action from watch_ciks a"
            " join (select cik, max(entry_id) as mid from watch_ciks group by cik) l"
            " on l.mid = a.entry_id order by a.cik"
        ).fetchall()
        return [WatchedCik(r[0], r[1], r[2], r[3]) for r in rows if r[4] == "allow"]

    def seed_from_file(self, path: Path) -> int:
        data = json.loads(path.read_text(encoding="utf-8"))
        added = 0
        for item in data["ciks"]:
            w = WatchedCik(item["cik"], item["name"], item["reason"], item["reviewer"])
            added += int(self.allow(w, source=path.name))
        return added


class SecWatcher:
    def __init__(self, client: SecClient, db: Db, locker: Locker, clock: Clock) -> None:
        self.client = client
        self.db = db
        self.locker = locker
        self.clock = clock
        self.ciks = CikWatchRepo(db, clock)

    # -- submissions JSON (authoritative) -----------------------------------------------------
    def poll_cik(self, cik: str) -> list[NewFiling]:
        """Poll one CIK. The first successful poll is a BASELINE: history is stored without a
        detection time and emits no events. Later polls emit one event per new accession."""
        _validate_cik(cik)
        source = f"sec:submissions:{cik}"
        started = time.monotonic()
        baseline = not has_ok_poll(self.db, source)
        now = self.clock.now()
        try:
            data = self.client.get_json(SUBMISSIONS.format(cik=cik))
            raw_count = len(data["filings"]["recent"]["accessionNumber"])
            parsed = parse_submissions(data)
            if baseline and len(parsed) < raw_count:
                # a baseline built from a partial parse would later report the rest as "new"
                raise ValueError(f"cannot parse {raw_count - len(parsed)} of {raw_count} rows")
        except Exception as exc:
            log_poll(
                self.db,
                now,
                source,
                ok=False,
                items=0,
                err=str(exc),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            raise
        # By accession across ALL CIKs: a filing can have several filers (co-registrants) and the
        # accession is the unique filing identity.
        known: dict[str, str | None] = {}
        accs = [f.accession for f in parsed]
        for i in range(0, len(accs), 500):
            chunk = accs[i : i + 500]
            marks = ",".join("?" * len(chunk))
            for r in self.db.conn.execute(
                f"select doc_id, accepted_at_utc from filings where source='sec'"
                f" and doc_id in ({marks})",
                chunk,
            ):
                known[r[0]] = r[1]
        events: list[NewFiling] = []
        with self.db.transaction():
            for f in parsed:
                if f.accession in known:
                    if (
                        known[f.accession] is None
                    ):  # discovered via Atom: fill the authoritative data
                        self.db.conn.execute(
                            "update filings set accepted_at_utc=?, filed_date=?, form=?,"
                            " primary_document=?, items=?, date_basis_differs=?, source_url=?"
                            " where source='sec' and doc_id=?",
                            (
                                f.accepted_at_utc.isoformat(),
                                f.filed_date.isoformat(),
                                f.form,
                                f.primary_document,
                                f.items,
                                int(f.date_basis_differs),
                                f.index_url,
                                f.accession,
                            ),
                        )
                    continue
                detected = None if baseline else now
                self.db.conn.execute(
                    "insert into filings(source, doc_id, cik, form, filed_date, accepted_at_utc,"
                    " posted_kind, acceptance_cross_checked, detected_at_utc, source_url,"
                    " discovered_via, primary_document, items, date_basis_differs)"
                    " values ('sec',?,?,?,?,?,'accepted',0,?,?,'submissions',?,?,?)",
                    (
                        f.accession,
                        cik,
                        f.form,
                        f.filed_date.isoformat(),
                        f.accepted_at_utc.isoformat(),
                        None if detected is None else detected.isoformat(),
                        f.index_url,
                        f.primary_document,
                        f.items,
                        int(f.date_basis_differs),
                    ),
                )
                if not baseline:
                    events.append(
                        NewFiling(
                            cik,
                            f.accession,
                            f.form,
                            f.filed_date,
                            f.accepted_at_utc,
                            now,
                            "submissions",
                            f.index_url,
                        )
                    )
            # inside the transaction: filings and the "this CIK is baselined" marker commit together
            log_poll(
                self.db,
                now,
                source,
                ok=True,
                items=len(parsed),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        return events

    # -- Atom feed (discovery only) -----------------------------------------------------------
    def poll_atom(self, form: str) -> list[NewFiling]:
        """Latest filings of one form. Entries of watched, baselined CIKs that we have not seen are
        recorded (acceptance time unknown until the submissions JSON confirms) and emitted."""
        source = f"sec:atom:{form}"
        started = time.monotonic()
        now = self.clock.now()
        try:
            text = self.client.get_text(
                ATOM, params={"action": "getcurrent", "type": form, "count": 40, "output": "atom"}
            )
            entries = parse_atom(text)
        except Exception as exc:
            log_poll(
                self.db,
                now,
                source,
                ok=False,
                items=0,
                err=str(exc),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            raise
        watched = {w.cik for w in self.ciks.snapshot()}
        events: list[NewFiling] = []
        with self.db.transaction():
            for e in entries:
                if e.cik not in watched or not has_ok_poll(self.db, f"sec:submissions:{e.cik}"):
                    continue
                exists = self.db.conn.execute(
                    "select 1 from filings where source='sec' and doc_id=?", (e.accession,)
                ).fetchone()
                if exists:
                    continue
                self.db.conn.execute(
                    "insert into filings(source, doc_id, cik, form, filed_date, accepted_at_utc,"
                    " posted_kind, acceptance_cross_checked, detected_at_utc, source_url,"
                    " discovered_via) values ('sec',?,?,?,?,NULL,'accepted',0,?,?,'atom')",
                    (
                        e.accession,
                        e.cik,
                        e.form,
                        e.filed_date.isoformat(),
                        now.isoformat(),
                        e.index_url,
                    ),
                )
                events.append(
                    NewFiling(
                        e.cik, e.accession, e.form, e.filed_date, None, now, "atom", e.index_url
                    )
                )
            log_poll(
                self.db,
                now,
                source,
                ok=True,
                items=len(entries),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        return events

    # -- documents ----------------------------------------------------------------------------
    def pending_primary(self, limit: int = 5) -> list[str]:
        """Accessions DETECTED by us (never baseline history) whose primary document is known but
        not stored yet: first fetch missed (404/5xx) or the filing was discovered via Atom."""
        rows = self.db.conn.execute(
            "select doc_id from filings where source='sec' and detected_at_utc is not null"
            " and primary_doc_sha is null and primary_document is not null"
            " and primary_document != ''"
            " order by detected_at_utc limit ?",
            (limit,),
        ).fetchall()
        return [r[0] for r in rows]

    def fetch_primary(self, accession: str) -> str | None:
        """Store a filing's primary document in the evidence locker (with the EDGAR acceptance time,
        separate from our fetch time). Returns the sha256, or None if there is nothing to fetch."""
        row: Any = self.db.conn.execute(
            "select cik, primary_document, primary_doc_sha, accepted_at_utc from filings"
            " where source='sec' and doc_id=?",
            (accession,),
        ).fetchone()
        if row is None:
            raise KeyError(accession)
        if row["primary_doc_sha"]:
            return str(row["primary_doc_sha"])
        if not row["primary_document"]:
            return None
        url = f"{ARCHIVES}/{int(row['cik'])}/{accession.replace('-', '')}/{row['primary_document']}"
        try:
            resp = self.client.get(url)
        except SecHTTPError as exc:
            if exc.status == 404:
                log.warning("primary document not found", extra={"url": url})
                return None
            raise
        if len(resp.body) > MAX_DOC_BYTES:
            log.warning("primary document too large; not stored", extra={"url": url})
            return None
        accepted = (
            datetime.fromisoformat(row["accepted_at_utc"]).astimezone(UTC)
            if row["accepted_at_utc"]
            else None
        )
        sha = self.locker.put(
            resp.body,
            kind="sec_primary_doc",
            source_url=url,
            fetched_at=self.clock.now(),
            accepted_at=accepted,
            accepted_at_source="submissions_json" if accepted else None,
        )
        self.db.conn.execute(
            "update filings set primary_doc_sha=? where source='sec' and doc_id=?", (sha, accession)
        )
        return sha
