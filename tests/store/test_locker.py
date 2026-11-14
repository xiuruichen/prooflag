import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from prooflag.store.db import Db
from prooflag.store.locker import IntegrityError, Locker

T = datetime(2026, 6, 1, 12, 0, 16, tzinfo=UTC)


def test_put_is_content_addressed_and_idempotent(db: Db, tmp_path: Path) -> None:
    lk = Locker(tmp_path / "locker", db)
    data = b"<html>8-K</html>"
    sha = lk.put(data, kind="sec_primary_doc", source_url="https://sec.gov/x", fetched_at=T)
    assert sha == hashlib.sha256(data).hexdigest()
    again = lk.put(data, kind="sec_primary_doc", source_url="https://other", fetched_at=T)
    assert again == sha
    assert db.conn.execute("select count(*) from artifacts").fetchone()[0] == 1
    assert sum(1 for p in (tmp_path / "locker").rglob("*") if p.is_file()) == 1
    assert lk.get(sha) == data


def test_path_is_sharded_by_sha_prefix(db: Db, tmp_path: Path) -> None:
    lk = Locker(tmp_path / "locker", db)
    sha = lk.put(b"abc", kind="k", source_url="u", fetched_at=T)
    assert (tmp_path / "locker" / sha[:2] / sha[2:4] / sha).is_file()


def test_acceptance_time_stored_separately_from_fetch_time(db: Db, tmp_path: Path) -> None:
    lk = Locker(tmp_path / "locker", db)
    acc = datetime(2026, 6, 1, 12, 0, 16, tzinfo=UTC)
    fetched = datetime(2026, 6, 1, 12, 0, 41, tzinfo=UTC)
    sha = lk.put(
        b"x",
        kind="k",
        source_url="u",
        fetched_at=fetched,
        accepted_at=acc,
        accepted_at_source="submissions_json",
    )
    row = db.conn.execute(
        "select fetched_at_utc, accepted_at_utc, accepted_at_source from artifacts where sha256=?",
        (sha,),
    ).fetchone()
    assert tuple(row) == (fetched.isoformat(), acc.isoformat(), "submissions_json")


def test_naive_datetimes_rejected(db: Db, tmp_path: Path) -> None:
    lk = Locker(tmp_path / "locker", db)
    with pytest.raises(ValueError, match="timezone"):
        lk.put(b"x", kind="k", source_url="u", fetched_at=datetime(2026, 1, 1))


def test_get_detects_tampering(db: Db, tmp_path: Path) -> None:
    lk = Locker(tmp_path / "locker", db)
    sha = lk.put(b"original", kind="k", source_url="u", fetched_at=T)
    (tmp_path / "locker" / sha[:2] / sha[2:4] / sha).write_bytes(b"tampered")
    with pytest.raises(IntegrityError):
        lk.get(sha)


def test_get_unknown_sha_raises_keyerror(db: Db, tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        Locker(tmp_path / "locker", db).get("0" * 64)
