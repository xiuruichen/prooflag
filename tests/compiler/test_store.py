from __future__ import annotations

import json
from datetime import UTC, datetime

from prooflag.clock import FixedClock
from prooflag.compiler.compile import compile_rule
from prooflag.compiler.store import latest_spec, store_spec
from prooflag.llm.provider import FakeProvider
from prooflag.store.db import Db
from prooflag.store.provenance import Provenance


def test_spec_is_stored_with_provenance_and_the_latest_is_read_back(db: Db) -> None:
    db.conn.execute(
        "insert into markets(venue, market_id, title, first_seen_at, last_seen_at)"
        " values ('kalshi','M1','t','2026-01-01','2026-01-01')"
    )
    prov = Provenance(db, FixedClock(datetime(2026, 6, 1, tzinfo=UTC)), code_version=("c", False))
    bad = FakeProvider("m", lambda s, u, sc: "not json")
    r = compile_rule("t", "Resolves by 11:59 PM ET on May 31, 2026.", None, [bad])
    sid = store_spec(db, prov, "kalshi", "M1", r)
    got = latest_spec(db, "kalshi", "M1")
    assert got is not None and got[0] == sid and got[2] is False
    assert got[1]["deadline_applies_to"] == "ambiguous"
    row = db.conn.execute(
        "select failed_checks_json, p.model_name from rule_specs s"
        " join provenance p using (provenance_id)"
    ).fetchone()
    assert json.loads(row[0])["model_errors"] == ["schema_invalid:m"] and row[1] == "m"
