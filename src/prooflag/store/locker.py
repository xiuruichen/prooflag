"""Append-only, content-addressed evidence locker (raw bytes on disk, index in SQLite)."""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime
from pathlib import Path

from prooflag.store.db import Db


class IntegrityError(Exception):
    """Stored bytes no longer match their sha256."""


def _iso(ts: datetime | None, name: str) -> str | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return ts.isoformat()


class Locker:
    def __init__(self, root: Path | str, db: Db) -> None:
        self.root = Path(root)
        self.db = db

    def _path(self, sha: str) -> Path:
        return self.root / sha[:2] / sha[2:4] / sha

    def put(
        self,
        data: bytes,
        *,
        kind: str,
        source_url: str | None,
        fetched_at: datetime,
        accepted_at: datetime | None = None,
        accepted_at_source: str | None = None,
        normalizer_ver: str | None = None,
    ) -> str:
        fetched = _iso(fetched_at, "fetched_at")
        accepted = _iso(accepted_at, "accepted_at")
        sha = hashlib.sha256(data).hexdigest()
        path = self._path(sha)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                try:
                    os.replace(tmp_name, path)
                except PermissionError:
                    # Windows: a concurrent writer holds the destination. Same bytes, same sha:
                    # if it exists now, that is success.
                    if not path.exists():
                        raise
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
        self.db.conn.execute(
            "insert or ignore into artifacts(sha256, kind, byte_len, path, source_url,"
            " fetched_at_utc, accepted_at_utc, accepted_at_source, normalizer_ver)"
            " values (?,?,?,?,?,?,?,?,?)",
            (
                sha,
                kind,
                len(data),
                str(path),
                source_url,
                fetched,
                accepted,
                accepted_at_source,
                normalizer_ver,
            ),
        )
        return sha

    def get(self, sha: str) -> bytes:
        row = self.db.conn.execute("select 1 from artifacts where sha256=?", (sha,)).fetchone()
        if row is None:
            raise KeyError(sha)
        data = self._path(sha).read_bytes()
        if hashlib.sha256(data).hexdigest() != sha:
            raise IntegrityError(f"locker content does not match sha256 {sha}")
        return data
