import sqlite3
from pathlib import Path

import pytest

from prooflag.store.db import Db

EXPECTED_TABLES = {
    "schema_version",
    "provenance",
    "market_clusters",
    "markets",
    "market_versions",
    "market_tags",
    "price_snapshots",
    "artifacts",
    "entities",
    "filings",
    "rule_specs",
    "evaluations",
    "llm_calls",
    "signals",
    "signal_events",
    "outcomes",
    "reviews",
    "poll_log",
    "labels_raw",
    "label_consensus",
    "market_rule_changes",
    "market_tokens",
    "watch_allowlist",
    "watch_candidates",
    "entity_aliases",
}


def test_migrate_creates_all_tables(db: Db) -> None:
    names = {r[0] for r in db.conn.execute("select name from sqlite_master where type='table'")}
    assert names >= EXPECTED_TABLES


def test_wal_and_foreign_keys_enabled(db: Db) -> None:
    assert db.conn.execute("pragma journal_mode").fetchone()[0].lower() == "wal"
    assert db.conn.execute("pragma foreign_keys").fetchone()[0] == 1


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    d = Db(tmp_path / "i.db")
    d.migrate()
    d.migrate()
    versions = [r[0] for r in d.conn.execute("select version from schema_version")]
    assert versions == sorted(set(versions))
    d.close()


def test_foreign_key_violation_rejected(db: Db) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute(
            "insert into market_tags(venue, market_id, tag, reason, matched_span)"
            " values ('kalshi','nope','sec','r','s')"
        )
