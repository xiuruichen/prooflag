"""Shared helpers for ingest tests (fixtures are recorded real responses)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ingest"
UA = "Prooflag/0.1 (research; read-only)"

Handler = Callable[[httpx.Request], httpx.Response]


def fixture(name: str) -> Any:
    """Load a recorded response. Wrapped fixtures ({status, body}) return the whole wrapper."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def body_of(name: str) -> Any:
    d = fixture(name)
    return d["body"] if isinstance(d, dict) and set(d) == {"status", "body"} else d


def json_response(obj: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=obj)
