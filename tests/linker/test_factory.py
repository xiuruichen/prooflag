from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from prooflag.clock import FixedClock
from prooflag.config import Settings
from prooflag.linker.factory import build_linker
from prooflag.store.db import Db

BODY = (
    Path(__file__).resolve().parent.parent / "fixtures" / "sec" / "company_tickers_subset.json"
).read_bytes()


def test_build_linker_loads_cache_seeds_aliases_and_resolves(tmp_path: Path) -> None:
    s = Settings(contact_email="real.person@example.org", data_dir=tmp_path, _env_file=None)
    db = Db(s.db_path)
    db.migrate()
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, content=BODY, headers={"Last-Modified": "x"})

    linker, info = build_linker(
        s,
        db,
        FixedClock(datetime(2026, 11, 14, tzinfo=UTC)),
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,
    )
    assert info.source == "network"
    assert linker.resolve("NVDA").cik == "0001045810"
    assert (
        linker.resolve("MicroStrategy").method == "alias"
    )  # seeded from config/entity_aliases.json
    assert seen[0].headers["user-agent"] == "Prooflag real.person@example.org"  # SEC only
    db.close()


def test_build_linker_refuses_to_run_without_a_real_contact(tmp_path: Path) -> None:
    s = Settings(contact_email="you@example.com", data_dir=tmp_path, _env_file=None)
    db = Db(s.db_path)
    db.migrate()
    with pytest.raises(ValueError, match="CONTACT"):
        build_linker(s, db, FixedClock(datetime(2026, 11, 14, tzinfo=UTC)))
    db.close()
