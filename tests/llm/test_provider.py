from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from prooflag.llm.provider import (
    CachedProvider,
    FakeProvider,
    ModelBusyError,
    ModelLock,
    OllamaProvider,
)
from prooflag.store.db import Db

SHA = "a" * 64
SCHEMA = {"type": "object", "properties": {"x": {"type": "string"}}}


def ollama(handler):  # type: ignore[no-untyped-def]
    return OllamaProvider("qwen3:8b", transport=httpx.MockTransport(handler))


def handler(req: httpx.Request) -> httpx.Response:
    body = json.loads(req.content)
    if req.url.path == "/api/show":
        return httpx.Response(
            200, json={"modelfile": f"FROM C:\\x\\blobs\\sha256-{SHA}\nPARAMETER a"}
        )
    handler.last = body  # type: ignore[attr-defined]
    return httpx.Response(200, json={"message": {"content": '{"x":"hi"}'}})


def test_ollama_request_is_deterministic_schema_constrained_and_thinking_off() -> None:
    p = ollama(handler)
    res = p.generate("SYS", "USER", SCHEMA, seed=7)
    b = handler.last  # type: ignore[attr-defined]
    assert b["format"] == SCHEMA and b["think"] is False and b["stream"] is False
    assert b["options"]["temperature"] == 0 and b["options"]["seed"] == 7
    assert [m["role"] for m in b["messages"]] == ["system", "user"]
    assert (
        res.text == '{"x":"hi"}' and res.model_sha256 == SHA and p.identity() == ("qwen3:8b", SHA)
    )


def test_cache_replays_identical_calls_and_separates_different_inputs(tmp_path: Path) -> None:
    db = Db(tmp_path / "c.db")
    db.migrate()
    inner = FakeProvider("m", lambda s, u, sc: json.dumps({"x": u}))
    c = CachedProvider(inner, db, lambda: datetime(2026, 1, 1, tzinfo=UTC))
    a1 = c.generate("S", "u1", SCHEMA)
    a2 = c.generate("S", "u1", SCHEMA)
    b = c.generate("S", "u2", SCHEMA)
    assert (a1.cached, a2.cached, b.cached) == (False, True, False) and inner.calls == 2
    assert a2.text == a1.text and b.text != a1.text
    assert c.generate("S2", "u1", SCHEMA).cached is False  # prompt template is part of the key
    assert db.conn.execute("select count(*) from llm_calls").fetchone()[0] == 3
    db.close()


def test_model_lock_is_exclusive_and_released(tmp_path: Path) -> None:
    lock = tmp_path / "model.lock"
    with ModelLock(lock, "benchmark"):
        with pytest.raises(ModelBusyError, match="owner=benchmark"), ModelLock(lock, "labeling"):
            pass
        assert lock.exists()
    assert not lock.exists()
    with ModelLock(lock):  # reusable after release
        pass


def test_model_lock_is_released_after_an_exception(tmp_path: Path) -> None:
    lock = tmp_path / "model.lock"
    with pytest.raises(RuntimeError), ModelLock(lock):
        raise RuntimeError("boom")
    assert not lock.exists()
