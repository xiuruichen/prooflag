"""One live ingest cycle against the real venues (manual validation; not used by tests).

Usage: python scripts/run_ingest_once.py [--skip-catalog]
Writes to the configured data dir (default data/prooflag.db, gitignored).
"""

from __future__ import annotations

import argparse
import time

from prooflag.clock import SystemClock
from prooflag.config import Settings
from prooflag.ingest.factory import build_service
from prooflag.logging import configure_logging
from prooflag.redact import default_redactor
from prooflag.store.db import Db


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-catalog", action="store_true")
    ap.add_argument("--backfill", type=int, default=25)
    args = ap.parse_args()
    configure_logging(redactor=default_redactor())
    settings = Settings()
    db = Db(settings.db_path)
    db.migrate()
    svc = build_service(settings, db, SystemClock())
    t0 = time.time()
    if not args.skip_catalog:
        for venue in ("kalshi", "polymarket"):
            print(venue, svc.catalog_pass(venue), f"{time.time() - t0:.0f}s", flush=True)
        for series in ("KXEOWEEK", "KXEOTRUMPTERM"):
            print(series, svc.ingest_series("kalshi", series), flush=True)
    print("snapshot", svc.snapshot_pass(), f"{time.time() - t0:.0f}s", flush=True)
    print("backfill", svc.backfill_pass(max_markets=args.backfill), f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
