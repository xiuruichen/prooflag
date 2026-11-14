import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from prooflag.logging import JsonFormatter
from prooflag.redact import Redactor
from prooflag.store.db import Db
from prooflag.store.locker import Locker

T = datetime(2026, 6, 1, tzinfo=UTC)


def test_concurrent_put_of_same_bytes_all_succeed(tmp_path: Path) -> None:
    db_path = tmp_path / "c.db"
    Db(db_path).migrate()
    data = b"x" * 2_000_000
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            d = Db(db_path)
            Locker(tmp_path / "locker", d).put(data, kind="k", source_url="u", fetched_at=T)
            d.close()
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors[:2]
    leftovers = [p for p in (tmp_path / "locker").rglob("*") if p.is_file() and p.suffix == ".tmp"]
    assert not leftovers
    assert sum(1 for p in (tmp_path / "locker").rglob("*") if p.is_file()) == 1


def test_concurrent_migrate_on_same_file_is_safe(tmp_path: Path) -> None:
    db_path = tmp_path / "m.db"
    errors: list[BaseException] = []
    barrier = threading.Barrier(6)

    def worker() -> None:
        try:
            barrier.wait()
            d = Db(db_path)
            d.migrate()
            d.close()
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors[:2]
    d = Db(db_path)
    versions = [r[0] for r in d.conn.execute("select version from schema_version")]
    assert versions == [1, 2, 3, 4, 5]
    d.close()


def test_recursive_triggers_enabled(db: Db) -> None:
    assert db.conn.execute("pragma recursive_triggers").fetchone()[0] == 1


def test_scrub_obj_scrubs_dict_keys_and_bytes_and_sets() -> None:
    r = Redactor(["me+x@ex.com"])
    out = r.scrub_obj({"me+x@ex.com": 1, "b": b"hi me+x@ex.com", "s": {"me+x@ex.com"}})
    blob = json.dumps(out, default=str)
    assert "me+x@ex.com" not in blob


def test_log_redacts_secrets_hidden_in_non_string_extras() -> None:
    class Obj:
        def __str__(self) -> str:
            return "obj me+x@ex.com"

    fmt = JsonFormatter(Redactor(["me+x@ex.com"]))
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "m", (), None)
    rec.o = Obj()
    rec.b = b"b me+x@ex.com"
    rec.s = {"me+x@ex.com"}
    rec.d = {"me+x@ex.com": 1}
    assert "me+x@ex.com" not in fmt.format(rec)


def test_raw_sqlite_error_type_is_database_error(db: Db) -> None:
    # sanity: the abort raised by triggers is catchable as sqlite3.DatabaseError
    with pytest.raises(sqlite3.DatabaseError):
        db.conn.execute("insert into schema_version(version, name, applied_at) values (1,'x','y')")
