"""SQLite connection (WAL, foreign keys) and numbered SQL migrations."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

from prooflag.clock import Clock, SystemClock


class Db:
    def __init__(self, path: Path | str, clock: Clock | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock or SystemClock()
        # isolation_level=None: autocommit; callers use explicit BEGIN where atomicity matters.
        self.conn = sqlite3.connect(self.path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma journal_mode=wal")
        self.conn.execute("pragma foreign_keys=on")
        self.conn.execute("pragma busy_timeout=5000")

    def close(self) -> None:
        self.conn.close()

    def migrate(self) -> list[int]:
        """Apply pending migrations in order; return the versions applied this call."""
        self.conn.execute(
            "create table if not exists schema_version("
            "version integer primary key, name text not null, applied_at text not null)"
        )
        done = {r[0] for r in self.conn.execute("select version from schema_version")}
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
            if version in done:
                continue
            sql = f.read_text(encoding="utf-8")
            self.conn.executescript(f"begin;\n{sql}\ncommit;")
            self.conn.execute(
                "insert into schema_version(version, name, applied_at) values (?,?,?)",
                (version, f.name, self._clock.now().isoformat()),
            )
            applied.append(version)
        return applied
