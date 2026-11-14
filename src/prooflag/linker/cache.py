"""Local cache of the SEC company_tickers.json with conditional revalidation."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from prooflag.clock import Clock
from prooflag.sec_client import SecClient

log = logging.getLogger(__name__)
URL = "https://www.sec.gov/files/company_tickers.json"


@dataclass(frozen=True)
class CacheInfo:
    source: str  # network | cache | cache-revalidated | stale-cache
    last_modified: str | None


def _valid(data: Any) -> bool:
    return (
        isinstance(data, dict)
        and bool(data)
        and all(
            isinstance(v, dict) and {"cik_str", "ticker", "title"} <= set(v) for v in data.values()
        )
    )


class SecTickerCache:
    def __init__(
        self, path: Path, client: SecClient, clock: Clock, max_age: timedelta = timedelta(hours=24)
    ) -> None:
        self.path = Path(path)
        self.meta_path = self.path.with_name(self.path.name + ".meta.json")
        self.client = client
        self.clock = clock
        self.max_age = max_age

    # -- helpers -----------------------------------------------------------------------------
    def _read(self) -> tuple[dict[str, Any], dict[str, Any]] | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not _valid(data):
            return None
        try:
            meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
            if not isinstance(meta, dict):
                meta = {}
        except (OSError, ValueError):
            meta = {}  # unreadable meta: keep the data, treat it as stale (refresh, or fall back)
        return data, meta

    def _write(self, body: bytes, last_modified: str | None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "wb") as fh:
            fh.write(body)
        os.replace(tmp, self.path)
        self._write_meta(last_modified)

    def _write_meta(self, last_modified: str | None) -> None:
        payload = json.dumps(
            {"last_modified": last_modified, "fetched_at": self.clock.now().isoformat()}
        )
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, self.meta_path)

    # -- API ---------------------------------------------------------------------------------
    def rows(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        cached = self._read()
        if cached is not None:
            data, meta = cached
            try:
                fetched = datetime.fromisoformat(meta["fetched_at"])
            except (KeyError, ValueError, TypeError):
                fetched = None  # no usable timestamp: stale
            if fetched is not None and self.clock.now() - fetched < self.max_age:
                return list(data.values()), CacheInfo("cache", meta.get("last_modified"))
        headers = {}
        if cached is not None and cached[1].get("last_modified"):
            headers["If-Modified-Since"] = cached[1]["last_modified"]
        try:
            resp = self.client.get(URL, headers=headers or None, allow_304=True)
        except Exception:
            if cached is not None:
                log.warning("company_tickers refresh failed; using stale cache", exc_info=True)
                return list(cached[0].values()), CacheInfo(
                    "stale-cache", cached[1].get("last_modified")
                )
            raise
        if resp.status == 304 and cached is not None:
            self._write_meta(cached[1].get("last_modified"))
            return list(cached[0].values()), CacheInfo(
                "cache-revalidated", cached[1].get("last_modified")
            )
        data = json.loads(resp.body)
        if not _valid(data):
            raise ValueError("company_tickers.json has an unexpected shape")
        last_modified = resp.headers.get("last-modified")
        self._write(resp.body, last_modified)
        return list(data.values()), CacheInfo("network", last_modified)
