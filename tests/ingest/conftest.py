from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fakes import Env, FakeSource
from ingest_helpers import UA, Handler

from prooflag.ingest.http import VenueClient


@pytest.fixture
def requests_log() -> list[httpx.Request]:
    return []


@pytest.fixture
def make_client(requests_log: list[httpx.Request]) -> Callable[[Handler], VenueClient]:
    def build(handler: Handler) -> VenueClient:
        def logging_handler(req: httpx.Request) -> httpx.Response:
            requests_log.append(req)
            return handler(req)

        return VenueClient(
            user_agent=UA,
            max_rps=1000.0,
            transport=httpx.MockTransport(logging_handler),
            sleep=lambda _s: None,
        )

    return build


@pytest.fixture
def make_env(tmp_path: Path) -> Iterator[Any]:
    envs: list[Env] = []

    def build(*sources: FakeSource) -> Env:
        e = Env(tmp_path, list(sources))
        envs.append(e)
        return e

    yield build
    for e in envs:
        e.db.close()
