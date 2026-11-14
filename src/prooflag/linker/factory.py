"""Wire the SEC client, ticker cache, reviewed aliases and linker from settings."""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from prooflag.clock import Clock
from prooflag.config import Settings
from prooflag.linker.cache import CacheInfo, SecTickerCache
from prooflag.linker.index import TickerIndex
from prooflag.linker.repo import AliasRepo
from prooflag.linker.resolve import EntityLinker
from prooflag.sec_client import SecClient
from prooflag.store.db import Db


def build_linker(
    settings: Settings,
    db: Db,
    clock: Clock,
    *,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[EntityLinker, CacheInfo]:
    settings.require_real_contact()  # the SEC needs a real contact in the User-Agent
    client = SecClient(
        user_agent=settings.user_agent,
        max_rps=settings.sec_max_rps,
        transport=transport,
        sleep=sleep,
    )
    rows, info = SecTickerCache(settings.data_dir / "company_tickers.json", client, clock).rows()
    aliases = AliasRepo(db, clock)
    if settings.entity_aliases_seed_path.exists():
        aliases.seed_from_file(settings.entity_aliases_seed_path)
    return EntityLinker(TickerIndex.from_rows(rows), aliases.snapshot()), info
