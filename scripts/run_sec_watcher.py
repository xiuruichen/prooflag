"""Run the SEC watcher in the foreground: polls watched CIKs (fast in the EDGAR window, slow
otherwise) and logs every new filing with its acceptance time and our detection lag.

Usage: uv run python scripts/run_sec_watcher.py [--once]
Stop with Ctrl+C. Needs PROOFLAG_CONTACT_EMAIL in .env (the SEC requires a real contact).
"""

from __future__ import annotations

import argparse
import logging
import time

from prooflag.clock import SystemClock
from prooflag.config import Settings
from prooflag.logging import configure_logging
from prooflag.redact import default_redactor
from prooflag.store.db import Db
from prooflag.watchers.factory import build_sec_service
from prooflag.watchers.sec import detection_lags

log = logging.getLogger("sec_watcher")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run a single tick and exit")
    args = ap.parse_args()
    configure_logging(redactor=default_redactor())
    settings = Settings()
    db = Db(settings.db_path)
    db.migrate()
    svc = build_sec_service(settings, db, SystemClock())
    log.info(
        "sec watcher started",
        extra={"ciks": [w.cik for w in svc.ciks.snapshot()], "forms": svc.atom_forms},
    )
    while True:
        res = svc.run_due()
        for f in res.new_filings:
            log.warning(
                "NEW FILING",
                extra={
                    "cik": f.cik,
                    "form": f.form,
                    "accession": f.accession,
                    "accepted_utc": f.accepted_at_utc and f.accepted_at_utc.isoformat(),
                    "detected_utc": f.detected_at_utc.isoformat(),
                    "lag_s": f.lag_seconds,
                    "via": f.discovered_via,
                },
            )
        if args.once:
            lags = detection_lags(db)
            print(
                {
                    "polled_ciks": res.polled_ciks,
                    "polled_atom": res.polled_atom,
                    "errors": res.errors,
                    "new": len(res.new_filings),
                    "lags": lags,
                }
            )
            return
        time.sleep(5)


if __name__ == "__main__":
    main()
