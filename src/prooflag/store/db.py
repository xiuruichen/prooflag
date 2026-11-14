"""SQLite connection (WAL, foreign keys) and numbered SQL migrations."""

from __future__ import annotations

import sqlite3
import time
from importlib import resources
from pathlib import Path

from prooflag.clock import Clock, SystemClock


class Db:
    def __init__(self, path: Path | str, clock: Clock | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock or SystemClock()
        # isolation_level=None: autocommit; callers use explicit BEGIN where atomicity matters.
        self.conn = sqlite3.connect(self.path, isolation_level=None, timeout=30)
        self.conn.row_factory = sqlite3.Row
        # busy_timeout first so the WAL pragma and everything after waits instead of failing.
        self.conn.execute("pragma busy_timeout=30000")
        self._enable_wal()
        self.conn.execute("pragma foreign_keys=on")
        # REPLACE only fires delete triggers when recursive triggers are on; the append-only
        # triggers rely on that to stop INSERT OR REPLACE from rewriting history.
        self.conn.execute("pragma recursive_triggers=on")

    def _enable_wal(self) -> None:
        # Switching a fresh file to WAL does not honor busy_timeout when another connection is
        # opening it at the same moment, so retry briefly.
        deadline = time.monotonic() + 30
        while True:
            try:
                self.conn.execute("pragma journal_mode=wal")
                return
            except sqlite3.OperationalError as e:
                if "locked" not in str(e) or time.monotonic() > deadline:
                    raise
                time.sleep(0.02)

    def close(self) -> None:
        self.conn.close()

    def _applied_versions(self) -> set[int]:
        return {r[0] for r in self.conn.execute("select version from schema_version")}

    def migrate(self) -> list[int]:
        """Apply pending migrations in order; return the versions applied this call.

        Safe against concurrent callers: each migration runs (with its schema_version row) in one
        `begin immediate` transaction; a loser of the race rolls back and re-checks.
        """
        self.conn.execute(
            "create table if not exists schema_version("
            "version integer primary key, name text not null, applied_at text not null)"
        )
        applied: list[int] = []
        files = sorted(
            (
                p
                for p in resources.files("prooflag.store").joinpath("migrations").iterdir()
                if p.name.endswith(".sql")
            ),
            key=lambda p: p.name,
        )
        for f in files:
            version = int(f.name.split("_", 1)[0])
            if version in self._applied_versions():
                continue
            sql = f.read_text(encoding="utf-8")
            stamp = self._clock.now().isoformat()
            record = (
                "insert into schema_version(version, name, applied_at) "
                f"values ({version}, '{f.name}', '{stamp}');"
            )
            try:
                self.conn.executescript(f"begin immediate;\n{sql}\n{record}\ncommit;")
            except sqlite3.DatabaseError:
                if self.conn.in_transaction:
                    self.conn.execute("rollback")
                if version in self._applied_versions():
                    continue  # another process applied it first
                raise
            applied.append(version)
        return applied
