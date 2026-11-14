"""Persist compiled specs (append-only) with provenance; read back the latest spec per market."""

from __future__ import annotations

import json

from prooflag.compiler.compile import CompileResult, spec_json
from prooflag.store.db import Db
from prooflag.store.provenance import Provenance


def store_spec(db: Db, prov: Provenance, venue: str, market_id: str, result: CompileResult) -> int:
    """Insert a rule_specs row. Both model identities go in the provenance inputs; the first
    model's file hash is the row's model_sha256."""
    name, sha = result.models[0] if result.models else (None, None)
    pid = prov.record(
        {
            "rules_sha": result.spec.rules_sha,
            "models": result.models,
            "outputs": result.raw_outputs,
        },
        model_name=name,
        model_sha256=sha,
        prompt_sha=result.prompt_sha,
    )
    with db.transaction() as c:
        cur = c.execute(
            "insert into rule_specs(venue, market_id, rules_sha, spec_json, valid,"
            " failed_checks_json, provenance_id) values (?,?,?,?,?,?,?)",
            (
                venue,
                market_id,
                result.spec.rules_sha,
                spec_json(result.spec),
                int(result.valid),
                json.dumps(result.failed_checks, sort_keys=True),
                pid,
            ),
        )
    assert cur.lastrowid is not None
    return cur.lastrowid


def latest_spec(db: Db, venue: str, market_id: str) -> tuple[int, dict[str, object], bool] | None:
    row = db.conn.execute(
        "select spec_id, spec_json, valid from rule_specs where venue=? and market_id=?"
        " order by spec_id desc limit 1",
        (venue, market_id),
    ).fetchone()
    return None if row is None else (row[0], json.loads(row[1]), bool(row[2]))
