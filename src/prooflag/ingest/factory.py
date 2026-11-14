"""Wire settings, HTTP client, sources, repo and service together."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import httpx

from prooflag.clock import Clock
from prooflag.config import Settings
from prooflag.ingest.allowlist import AllowlistRepo
from prooflag.ingest.cadence import Cadence
from prooflag.ingest.http import VenueClient
from prooflag.ingest.kalshi import KalshiSource
from prooflag.ingest.polymarket import PolymarketSource
from prooflag.ingest.repo import MarketRepo
from prooflag.ingest.service import IngestService
from prooflag.store.db import Db
from prooflag.store.locker import Locker


def build_service(
    settings: Settings,
    db: Db,
    clock: Clock,
    *,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    seed_path: Path | None = None,
) -> IngestService:
    # One client (one shared rate limiter) for both venues, with the GENERIC user agent: the SEC
    # contact email is never sent to Kalshi or Polymarket.
    client = VenueClient(
        user_agent=settings.venue_user_agent,
        max_rps=settings.venue_max_rps,
        transport=transport,
        sleep=sleep,
    )
    sources = {
        "kalshi": KalshiSource(client, settings.kalshi_base),
        "polymarket": PolymarketSource(client, settings.gamma_base, settings.clob_base, clock.now),
    }
    repo = MarketRepo(db, Locker(settings.locker_dir, db), clock)
    allowlist = AllowlistRepo(db, clock)
    seed = seed_path if seed_path is not None else settings.allowlist_seed_path
    if seed.exists():
        allowlist.seed_from_file(seed)  # idempotent: only entries not already active are added
    return IngestService(
        db,
        repo,
        clock,
        sources,
        cadence=Cadence(
            settings.edgar_window_start,
            settings.edgar_window_end,
            settings.snapshot_fast_minutes,
            settings.snapshot_slow_minutes,
        ),
        min_vol24_usd=settings.min_vol24_usd,
        catalog_interval=timedelta(minutes=settings.catalog_interval_minutes),
        allowlist=allowlist,
    )
