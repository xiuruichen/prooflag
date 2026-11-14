import json
from datetime import UTC, datetime

from prooflag.clock import FixedClock
from prooflag.redact import Redactor
from prooflag.store.db import Db
from prooflag.store.provenance import Provenance


def test_record_stores_hashes_model_prompt_and_code_version(db: Db) -> None:
    clock = FixedClock(datetime(2026, 6, 1, tzinfo=UTC))
    prov = Provenance(db, clock, code_version=("deadbeef", True))
    pid = prov.record(
        {"rules_sha": "r1", "doc_sha": "d1"},
        model_name="qwen3:8b",
        model_sha256="m" * 64,
        prompt_sha="p" * 64,
    )
    row = db.conn.execute(
        "select input_hashes_json, model_name, model_sha256, prompt_sha, code_git_sha, dirty,"
        " created_at from provenance where provenance_id=?",
        (pid,),
    ).fetchone()
    assert json.loads(row[0]) == {"doc_sha": "d1", "rules_sha": "r1"}
    assert tuple(row)[1:6] == ("qwen3:8b", "m" * 64, "p" * 64, "deadbeef", 1)
    assert row[6] == "2026-06-01T00:00:00+00:00"


def test_record_redacts_secrets_in_inputs(db: Db) -> None:
    clock = FixedClock(datetime(2026, 6, 1, tzinfo=UTC))
    prov = Provenance(db, clock, code_version=("abc", False), redactor=Redactor(["s3cret@x.io"]))
    pid = prov.record({"ua": "Prooflag s3cret@x.io"})
    blob = db.conn.execute(
        "select input_hashes_json from provenance where provenance_id=?", (pid,)
    ).fetchone()[0]
    assert "s3cret@x.io" not in blob


def test_default_code_version_reads_git_sha() -> None:
    sha, dirty = Provenance.detect_code_version()
    assert len(sha) in (7, 40) or sha == "unknown"
    assert isinstance(dirty, bool)
