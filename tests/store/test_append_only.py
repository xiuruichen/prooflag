import sqlite3

import pytest

from prooflag.store.db import Db

NOW = "2026-01-01T00:00:00+00:00"

APPEND_ONLY = [
    "market_versions",
    "price_snapshots",
    "artifacts",
    "rule_specs",
    "evaluations",
    "llm_calls",
    "signal_events",
    "provenance",
    "labels_raw",
    "label_consensus",
]


def _seed(db: Db) -> dict[str, tuple[str, tuple[object, ...]]]:
    c = db.conn
    c.execute(
        "insert into provenance(input_hashes_json, code_git_sha, dirty, created_at)"
        " values ('{}','abc',0,?)",
        (NOW,),
    )
    c.execute(
        "insert into markets(venue, market_id, title, first_seen_at, last_seen_at)"
        " values ('kalshi','m1','t',?,?)",
        (NOW, NOW),
    )
    c.execute(
        "insert into rule_specs(venue, market_id, rules_sha, spec_json, valid, provenance_id)"
        " values ('kalshi','m1','r1','{}',1,1)"
    )
    c.execute(
        "insert into signals(type, venue, market_id, rules_sha, dedupe_key, shadow, status,"
        " created_at) values ('ambiguity','kalshi','m1','r1','k1',1,'open',?)",
        (NOW,),
    )
    return {
        "market_versions": (
            "insert into market_versions(venue, market_id, rules_sha, rules_text, seen_at)"
            " values ('kalshi','m1','r1','rules',?)",
            (NOW,),
        ),
        "price_snapshots": (
            "insert into price_snapshots(venue, market_id, outcome, ts_utc, price, volume,"
            " open_interest, source) values ('kalshi','m1','yes',?,0.5,1,1,'snapshot')",
            (NOW,),
        ),
        "artifacts": (
            "insert into artifacts(sha256, kind, byte_len, path, source_url, fetched_at_utc)"
            " values ('aa','html',1,'p','u',?)",
            (NOW,),
        ),
        "rule_specs": (
            "insert into rule_specs(venue, market_id, rules_sha, spec_json, valid, provenance_id)"
            " values ('kalshi','m1','r2','{}',1,1)",
            (),
        ),
        "evaluations": (
            "insert into evaluations(spec_id, source, doc_id, doc_sha, decision, gate_json,"
            " final_decision, provenance_id) values (1,'sec','d','aa','yes','{}','yes',1)",
            (),
        ),
        "llm_calls": (
            "insert into llm_calls(input_sha, model_name, model_file_sha256, prompt_tmpl_sha,"
            " params_json, output_text, output_sha, latency_ms, created_at)"
            " values ('i','m','f','p','{}','o','os',1,?)",
            (NOW,),
        ),
        "signal_events": (
            "insert into signal_events(signal_id, ts, event, reason) values (1,?,'fired','ok')",
            (NOW,),
        ),
        "provenance": (
            "insert into provenance(input_hashes_json, code_git_sha, dirty, created_at)"
            " values ('{}','def',0,?)",
            (NOW,),
        ),
        "labels_raw": (
            "insert into labels_raw(item_kind, item_id, labeler, model, value_json, spans_json,"
            " reason, spans_valid, provenance_id, created_at)"
            " values ('rule','i1','A','opus','{}','[]','r',1,1,?)",
            (NOW,),
        ),
        "label_consensus": (
            "insert into label_consensus(item_kind, item_id, status, value_json,"
            " agreement_pattern, provenance_id, created_at)"
            " values ('rule','i1','ai_consensus','{}','3/3',1,?)",
            (NOW,),
        ),
    }


@pytest.mark.parametrize("table", APPEND_ONLY)
def test_update_and_delete_are_rejected(db: Db, table: str) -> None:
    sql, params = _seed(db)[table]
    db.conn.execute(sql, params)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.conn.execute(f"update {table} set rowid = rowid + 1000")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.conn.execute(f"delete from {table}")


@pytest.mark.parametrize("table", APPEND_ONLY)
def test_replace_cannot_overwrite_history(db: Db, table: str) -> None:
    sql, params = _seed(db)[table]
    db.conn.execute(sql, params)
    # REPLACE deletes the conflicting row; without recursive_triggers the delete trigger is skipped.
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.conn.execute(f"insert or replace into {table} select * from {table}")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.conn.execute(f"replace into {table} select * from {table}")


def test_mutable_tables_still_updatable(db: Db) -> None:
    _seed(db)
    db.conn.execute("update markets set title='new' where market_id='m1'")
    assert db.conn.execute("select title from markets").fetchone()[0] == "new"
