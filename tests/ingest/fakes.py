"""Shared fakes for service-level ingest tests."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from prooflag.clock import FixedClock
from prooflag.ingest.allowlist import AllowEntry, AllowlistRepo
from prooflag.ingest.cadence import Cadence
from prooflag.ingest.models import PricePoint, RawMarket
from prooflag.ingest.repo import MarketRepo
from prooflag.ingest.service import IngestService
from prooflag.store.db import Db
from prooflag.store.locker import Locker

T0 = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)  # Friday 10:00 ET: inside the EDGAR window


class FakeSource:
    def __init__(self, venue: str, markets: list[RawMarket]) -> None:
        self.venue = venue
        self.catalog = markets
        self.lookups: dict[str, RawMarket] = {m.market_id: m for m in markets}
        self.lookup_calls: list[list[str]] = []
        self.history_calls: list[dict[str, Any]] = []
        self.series_calls: list[tuple[str, str | None]] = []
        self.fail_lookup = False

    def iter_markets(
        self, *, status: str = "open", series_ticker: str | None = None
    ) -> Iterator[RawMarket]:
        self.series_calls.append((status, series_ticker))
        for m in self.catalog:
            if series_ticker and m.series_ticker != series_ticker:
                continue
            if status == "open" or m.status == status:
                yield copy.deepcopy(m)

    def fetch_markets(self, ids: list[str]) -> list[RawMarket]:
        if self.fail_lookup:
            raise RuntimeError("venue down")
        self.lookup_calls.append(list(ids))
        return [copy.deepcopy(self.lookups[i]) for i in ids if i in self.lookups]

    def history(
        self,
        *,
        market_id: str,
        series_ticker: str | None,
        token_id: str | None,
        start: datetime,
        end: datetime,
    ) -> list[PricePoint]:
        self.history_calls.append(
            {
                "id": market_id,
                "series": series_ticker,
                "token": token_id,
                "start": start,
                "end": end,
            }
        )
        return [
            PricePoint(ts=start + timedelta(hours=i), price=0.3, yes_bid=0.2, yes_ask=0.4)
            for i in range(3)
        ]


def mk(market_id: str, **kw: Any) -> RawMarket:
    base: dict[str, Any] = dict(
        venue="kalshi",
        market_id=market_id,
        title=f"title {market_id}",
        rules_primary="Resolved per the Federal Register.",
        event_id="EV-" + market_id,
        event_title="ev",
        series_ticker="S",
        status="open",
        yes_bid=0.1,
        yes_ask=0.2,
        last_price=0.15,
        vol24_contracts=100.0,
        vol24_usd_est=5000.0,
        raw={"id": market_id},
        open_time=T0 - timedelta(days=3),
        close_time=T0 + timedelta(days=2),
    )
    base.update(kw)
    return RawMarket(**base)


class Env:
    def __init__(self, tmp_path: Path, sources: list[FakeSource]) -> None:
        self.db = Db(tmp_path / "s.db")
        self.db.migrate()
        self.clock = FixedClock(T0)
        self.repo = MarketRepo(self.db, Locker(tmp_path / "lk", self.db), self.clock)
        self.sources = {s.venue: s for s in sources}
        self.allowlist = AllowlistRepo(self.db, self.clock)
        self.svc = IngestService(
            self.db,
            self.repo,
            self.clock,
            self.sources,
            cadence=Cadence(),
            min_vol24_usd=1000.0,
            batch_size=2,
            allowlist=self.allowlist,
        )

    def allow_catalog(self) -> None:
        """Allow-list every market the fake sources serve (most tests are about what happens to
        watched markets, not about who gets watched)."""
        for src in self.sources.values():
            for m in src.catalog:
                self.allow(src.venue, m.market_id)
            for mid in src.lookups:
                self.allow(src.venue, mid)

    def allow(self, venue: str, key: str, scope: str = "market") -> None:
        self.allowlist.allow(AllowEntry(venue, scope, key, "test fixture", "tests"))

    def one(self, sql: str, *a: Any) -> Any:
        return self.db.conn.execute(sql, a).fetchone()
