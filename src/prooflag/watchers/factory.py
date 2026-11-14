"""Wire the SEC watcher service from settings."""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from prooflag.clock import Clock
from prooflag.config import Settings
from prooflag.ingest.cadence import Cadence
from prooflag.sec_client import SecClient
from prooflag.store.db import Db
from prooflag.store.locker import Locker
from prooflag.watchers.sec import CikWatchRepo, SecWatcher
from prooflag.watchers.sec_service import SecService


def build_sec_service(
    settings: Settings,
    db: Db,
    clock: Clock,
    *,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> SecService:
    settings.require_real_contact()  # the SEC needs a real contact in the User-Agent
    client = SecClient(
        user_agent=settings.user_agent,
        max_rps=settings.sec_max_rps,
        transport=transport,
        sleep=sleep,
    )
    watcher = SecWatcher(client, db, Locker(settings.locker_dir, db), clock)
    ciks = CikWatchRepo(db, clock)
    if settings.watch_ciks_seed_path.exists():
        ciks.seed_from_file(settings.watch_ciks_seed_path)
    cadence = Cadence(
        settings.edgar_window_start,
        settings.edgar_window_end,
        settings.sec_fast_seconds / 60.0,
        float(settings.sec_slow_minutes),
    )
    return SecService(db, watcher, ciks, clock, cadence=cadence, atom_forms=settings.atom_forms)
