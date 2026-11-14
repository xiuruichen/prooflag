"""Persistence for entity links, the review queue and reviewed aliases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from prooflag.clock import Clock
from prooflag.linker.normalize import normalize_name
from prooflag.linker.resolve import Alias, LinkResult
from prooflag.store.db import Db


class EntityRepo:
    def __init__(self, db: Db, clock: Clock) -> None:
        self.db = db
        self.clock = clock

    def record(self, r: LinkResult) -> int:
        """Upsert by query. Resolved rows carry the company name, CIK and first ticker; ambiguous
        and unresolved rows keep their candidates for review."""
        company = r.candidates[0] if r.status == "resolved" and r.candidates else None
        cands = [{"cik": c.cik, "name": c.name, "tickers": list(c.tickers)} for c in r.candidates]
        cur = self.db.conn.execute(
            "insert into entities(query, name, cik, ticker, link_status, candidates_json,"
            " link_method, updated_at) values (?,?,?,?,?,?,?,?)"
            " on conflict(query) do update set name=excluded.name, cik=excluded.cik,"
            " ticker=excluded.ticker, link_status=excluded.link_status,"
            " candidates_json=excluded.candidates_json, link_method=excluded.link_method,"
            " updated_at=excluded.updated_at",
            (
                r.query,
                company.name if company else None,
                r.cik,
                company.tickers[0] if company and company.tickers else None,
                r.status,
                json.dumps(cands),
                r.method,
                self.clock.now().isoformat(),
            ),
        )
        row = self.db.conn.execute(
            "select entity_id from entities where query=?", (r.query,)
        ).fetchone()
        assert cur is not None and row is not None
        return int(row[0])

    def review_queue(self) -> list[dict[str, Any]]:
        rows = self.db.conn.execute(
            "select * from entities where link_status != 'resolved' order by link_status, query"
        ).fetchall()
        return [dict(r) for r in rows]


class AliasRepo:
    def __init__(self, db: Db, clock: Clock) -> None:
        self.db = db
        self.clock = clock

    def _latest(self, norm: str) -> str | None:
        row = self.db.conn.execute(
            "select action from entity_aliases where alias_norm=? order by alias_id desc limit 1",
            (norm,),
        ).fetchone()
        return None if row is None else str(row[0])

    def _append(self, action: str, a: Alias, source: str | None) -> bool:
        norm = normalize_name(a.alias)
        if self._latest(norm) == action:
            return False
        self.db.conn.execute(
            "insert into entity_aliases(action, alias_norm, alias_raw, cik, name, reason, reviewer,"
            " added_at, source) values (?,?,?,?,?,?,?,?,?)",
            (
                action,
                norm,
                a.alias,
                a.cik,
                a.name,
                a.reason,
                a.reviewer,
                self.clock.now().isoformat(),
                source,
            ),
        )
        return True

    def add(self, a: Alias, source: str | None = None) -> bool:
        return self._append("allow", a, source)

    def revoke(self, a: Alias, source: str | None = None) -> bool:
        return self._append("revoke", a, source)

    def snapshot(self) -> list[Alias]:
        rows = self.db.conn.execute(
            "select a.alias_raw, a.cik, a.name, a.reason, a.reviewer, a.action"
            " from entity_aliases a join (select alias_norm, max(alias_id) as mid"
            " from entity_aliases group by alias_norm) l on l.mid = a.alias_id"
        ).fetchall()
        return [Alias(r[0], r[1], r[2], r[3], r[4]) for r in rows if r[5] == "allow"]

    def seed_from_file(self, path: Path) -> int:
        data = json.loads(path.read_text(encoding="utf-8"))
        added = 0
        for item in data["aliases"]:
            alias = Alias(
                item["alias"], item["cik"], item["name"], item["reason"], item["reviewer"]
            )
            added += int(self.add(alias, source=path.name))
        return added
