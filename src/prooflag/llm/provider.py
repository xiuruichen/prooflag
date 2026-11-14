"""LLM provider interface, Ollama implementation, cache, fake, and the exclusive model lock."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol

import httpx

from prooflag.store.db import Db


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LLMResult:
    text: str
    model_name: str
    model_sha256: str
    latency_ms: int
    cached: bool = False


class LLMProvider(Protocol):
    model_name: str

    def identity(self) -> tuple[str, str]:
        """(model name, model file sha256)."""

    def generate(
        self, system: str, user: str, schema: dict[str, Any], *, seed: int = 42
    ) -> LLMResult: ...


class OllamaProvider:
    """Ollama /api/chat with JSON-schema constrained output, thinking off, temperature 0."""

    def __init__(
        self,
        model: str,
        endpoint: str = "http://127.0.0.1:11434",
        *,
        num_ctx: int = 4096,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 900.0,
    ) -> None:
        self.model_name = model
        self._num_ctx = num_ctx
        self._http = httpx.Client(base_url=endpoint, transport=transport, timeout=timeout)
        self._sha: str | None = None

    def identity(self) -> tuple[str, str]:
        if self._sha is None:
            r = self._http.post("/api/show", json={"model": self.model_name})
            r.raise_for_status()
            m = re.search(r"FROM\s+\S*sha256-([0-9a-f]{64})", r.json().get("modelfile", ""))
            if not m:
                raise RuntimeError(f"cannot find the model file sha256 for {self.model_name}")
            self._sha = m.group(1)
        return self.model_name, self._sha

    def generate(
        self, system: str, user: str, schema: dict[str, Any], *, seed: int = 42
    ) -> LLMResult:
        name, sha = self.identity()
        t0 = time.monotonic()
        r = self._http.post(
            "/api/chat",
            json={
                "model": name,
                "stream": False,
                "think": False,
                "format": schema,
                "options": {"temperature": 0, "seed": seed, "num_ctx": self._num_ctx},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        r.raise_for_status()
        return LLMResult(
            r.json()["message"]["content"], name, sha, int((time.monotonic() - t0) * 1000)
        )


class FakeProvider:
    """Scripted outputs for tests: ``respond(system, user, schema) -> text``."""

    def __init__(
        self,
        model_name: str,
        respond: Callable[[str, str, dict[str, Any]], str],
        sha: str = "f" * 64,
    ) -> None:
        self.model_name = model_name
        self._respond = respond
        self._sha = sha
        self.calls = 0

    def identity(self) -> tuple[str, str]:
        return self.model_name, self._sha

    def generate(
        self, system: str, user: str, schema: dict[str, Any], *, seed: int = 42
    ) -> LLMResult:
        self.calls += 1
        return LLMResult(self._respond(system, user, schema), self.model_name, self._sha, 0)


class CachedProvider:
    """Replay support: identical (input, model file, prompt template, params) never re-infers."""

    def __init__(self, inner: LLMProvider, db: Db, now: Callable[[], datetime]) -> None:
        self._inner = inner
        self._db = db
        self._now = now
        self.model_name = inner.model_name

    def identity(self) -> tuple[str, str]:
        return self._inner.identity()

    def generate(
        self, system: str, user: str, schema: dict[str, Any], *, seed: int = 42
    ) -> LLMResult:
        name, sha = self._inner.identity()
        params = json.dumps({"seed": seed, "temperature": 0, "think": False}, sort_keys=True)
        input_sha = sha256_text(json.dumps({"user": user, "schema": schema}, sort_keys=True))
        tmpl_sha = sha256_text(system)
        row = self._db.conn.execute(
            "select output_text, latency_ms from llm_calls"
            " where input_sha=? and model_file_sha256=?"
            " and prompt_tmpl_sha=? and params_json=?",
            (input_sha, sha, tmpl_sha, params),
        ).fetchone()
        if row is not None:
            return LLMResult(row[0], name, sha, int(row[1] or 0), cached=True)
        res = self._inner.generate(system, user, schema, seed=seed)
        self._db.conn.execute(
            "insert or ignore into llm_calls(input_sha, model_name, model_file_sha256,"
            " prompt_tmpl_sha, params_json, output_text, output_sha, latency_ms, created_at)"
            " values (?,?,?,?,?,?,?,?,?)",
            (
                input_sha,
                name,
                sha,
                tmpl_sha,
                params,
                res.text,
                sha256_text(res.text),
                res.latency_ms,
                self._now().isoformat(),
            ),
        )
        return res


class ModelBusyError(Exception):
    """Another model job holds the lock."""


class ModelLock:
    """Exclusive lock file: only one heavy model job runs at a time."""

    def __init__(self, path: Path, owner: str = "") -> None:
        self.path = Path(path)
        self.owner = owner

    def __enter__(self) -> ModelLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as e:
            holder = self.path.read_text(encoding="utf-8", errors="replace")[:200]
            raise ModelBusyError(f"model lock held ({self.path}): {holder}") from e
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"pid={os.getpid()} owner={self.owner}")
        return self

    def __exit__(
        self, et: type[BaseException] | None, ev: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.path.unlink(missing_ok=True)
