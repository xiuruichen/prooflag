"""Resolve names/tickers to CIKs against the live SEC file and record them (manual check).

Usage: python scripts/link_entities.py "Anthropic" "OpenAI" NVDA ...
Prints the status; ambiguous/unresolved go to the review queue (entities table).
"""

from __future__ import annotations

import sys

from prooflag.clock import SystemClock
from prooflag.config import Settings
from prooflag.linker.factory import build_linker
from prooflag.linker.repo import EntityRepo
from prooflag.store.db import Db


def main() -> None:
    settings = Settings()
    db = Db(settings.db_path)
    db.migrate()
    clock = SystemClock()
    linker, info = build_linker(settings, db, clock)
    print(f"ticker file: {info.source} (last-modified {info.last_modified})")
    repo = EntityRepo(db, clock)
    for q in sys.argv[1:]:
        r = linker.resolve(q)
        repo.record(r)
        cands = ", ".join(f"{c.name} [{c.cik}]" for c in r.candidates[:3])
        print(f"{q!r}: {r.status} cik={r.cik} via {r.method}  {cands}")
    print("review queue:", [e["query"] for e in repo.review_queue()])


if __name__ == "__main__":
    main()
