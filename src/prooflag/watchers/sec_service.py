"""Adaptive SEC polling: fast in the EDGAR window, slow otherwise, with per-source backoff."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from prooflag.clock import Clock
from prooflag.ingest.cadence import Cadence
from prooflag.scheduling import backoff_due, log_poll
from prooflag.store.db import Db
from prooflag.watchers.sec import CikWatchRepo, NewFiling, SecWatcher

log = logging.getLogger(__name__)


@dataclass
class SecRunResult:
    polled_ciks: int = 0
    polled_atom: int = 0
    errors: int = 0
    new_filings: list[NewFiling] = field(default_factory=list)


class SecService:
    def __init__(
        self,
        db: Db,
        watcher: SecWatcher,
        ciks: CikWatchRepo,
        clock: Clock,
        *,
        cadence: Cadence,
        atom_forms: Sequence[str],
    ) -> None:
        self.db = db
        self.watcher = watcher
        self.ciks = ciks
        self.clock = clock
        self.cadence = cadence
        self.atom_forms = tuple(atom_forms)

    def run_due(self) -> SecRunResult:
        """One tick. Never raises: errors are logged to poll_log (via the watcher) and trigger
        exponential backoff for that source only."""
        res = SecRunResult()
        now = self.clock.now()
        base = self.cadence.interval(now)
        for w in self.ciks.snapshot():
            if not backoff_due(self.db, f"sec:submissions:{w.cik}", base, now):
                continue
            res.polled_ciks += 1
            try:
                res.new_filings += self.watcher.poll_cik(w.cik)
            except Exception:
                res.errors += 1
                log.exception("sec submissions poll failed", extra={"cik": w.cik})
        for form in self.atom_forms:
            if not backoff_due(self.db, f"sec:atom:{form}", base, now):
                continue
            res.polled_atom += 1
            try:
                res.new_filings += self.watcher.poll_atom(form)
            except Exception:
                res.errors += 1
                log.exception("sec atom poll failed", extra={"form": form})
        # Every detected filing whose primary document is still missing (event tick missed it, or it
        # was discovered via Atom before the submissions JSON named the document), with a
        # per-accession backoff so a missing document is not requested every tick.
        for acc in self.watcher.pending_primary():
            if not backoff_due(self.db, f"sec:doc:{acc}", base, now):
                continue
            started = time.monotonic()
            try:
                sha = self.watcher.fetch_primary(acc)
                ok, err = sha is not None, None if sha is not None else "not available yet"
            except Exception as exc:
                res.errors += 1
                ok, err = False, str(exc)
                log.exception("primary document fetch failed", extra={"accession": acc})
            log_poll(
                self.db,
                now,
                f"sec:doc:{acc}",
                ok=ok,
                items=int(ok),
                err=err,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        return res
