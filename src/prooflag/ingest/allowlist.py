"""Curated watch allow-list (append-only, with reason + reviewer) and its seed file."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from prooflag.clock import Clock
from prooflag.ingest.models import RawMarket
from prooflag.store.db import Db

SCOPES = ("market", "event", "series")


@dataclass(frozen=True)
class AllowEntry:
    venue: str
    scope: str
    key: str
    reason: str
    reviewer: str


class AllowList:
    """Immutable snapshot of the active entries, used for matching during a pass."""

    def __init__(self, entries: list[AllowEntry]) -> None:
        self._by_key = {(e.venue, e.scope, e.key): e for e in entries}

    def __len__(self) -> int:
        return len(self._by_key)

    def match(self, m: RawMarket) -> AllowEntry | None:
        for scope, key in (
            ("market", m.market_id),
            ("event", m.event_id),
            ("series", m.series_ticker),
        ):
            if key and (hit := self._by_key.get((m.venue, scope, key))):
                return hit
        return None

    def market_ids(self, venue: str) -> list[str]:
        return sorted(k for (v, s, k) in self._by_key if v == venue and s == "market")


class AllowlistRepo:
    def __init__(self, db: Db, clock: Clock) -> None:
        self.db = db
        self.clock = clock

    def _latest(self, venue: str, scope: str, key: str) -> tuple[str, str, str] | None:
        row = self.db.conn.execute(
            "select action, reason, reviewer from watch_allowlist"
            " where venue=? and scope=? and key=? order by entry_id desc limit 1",
            (venue, scope, key),
        ).fetchone()
        return None if row is None else (row[0], row[1], row[2])

    def _append(self, action: str, e: AllowEntry, source: str | None) -> bool:
        if e.scope not in SCOPES:
            raise ValueError(f"bad scope {e.scope!r}")
        if not e.reason.strip() or not e.reviewer.strip():
            raise ValueError("allow-list entries need a reason and a reviewer")
        latest = self._latest(e.venue, e.scope, e.key)
        if latest is not None and latest[0] == action:
            return False  # already in that state: no-op, history stays clean
        self.db.conn.execute(
            "insert into watch_allowlist(action, venue, scope, key, reason, reviewer, added_at,"
            " source) values (?,?,?,?,?,?,?,?)",
            (
                action,
                e.venue,
                e.scope,
                e.key,
                e.reason,
                e.reviewer,
                self.clock.now().isoformat(),
                source,
            ),
        )
        return True

    def allow(self, e: AllowEntry, source: str | None = None) -> bool:
        return self._append("allow", e, source)

    def revoke(self, e: AllowEntry, source: str | None = None) -> bool:
        return self._append("revoke", e, source)

    def snapshot(self) -> AllowList:
        rows = self.db.conn.execute(
            "select a.venue, a.scope, a.key, a.reason, a.reviewer, a.action"
            " from watch_allowlist a join (select venue, scope, key, max(entry_id) as eid"
            "   from watch_allowlist group by venue, scope, key) l on l.eid = a.entry_id"
        ).fetchall()
        return AllowList(
            [AllowEntry(r[0], r[1], r[2], r[3], r[4]) for r in rows if r[5] == "allow"]
        )

    def seed_from_file(self, path: Path) -> int:
        """Append entries from a seed file that are not already active. Idempotent."""
        data = json.loads(path.read_text(encoding="utf-8"))
        added = 0
        for item in data["entries"]:
            entry = AllowEntry(
                item["venue"], item["scope"], item["key"], item["reason"], item["reviewer"]
            )
            added += int(self.allow(entry, source=path.name))
        return added
