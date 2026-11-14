"""Ingest orchestration: catalog passes, series ingest, price snapshots, history backfill."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from prooflag.clock import Clock
from prooflag.ingest.allowlist import AllowList, AllowlistRepo
from prooflag.ingest.cadence import Cadence
from prooflag.ingest.models import PricePoint, RawMarket
from prooflag.ingest.repo import MarketRepo
from prooflag.ingest.tagging import (
    EO_TERM_SERIES,
    WEEKLY_EO_SERIES,
    assign_cluster,
    is_meaningful,
    is_review_candidate,
    tag_market,
)
from prooflag.store.db import Db

log = logging.getLogger(__name__)
SERIES_STATUSES = ("open", "closed", "settled")
PRIMARY_SERIES = (WEEKLY_EO_SERIES, EO_TERM_SERIES)


class Source(Protocol):
    venue: str

    def iter_markets(self, **kw: Any) -> Iterator[RawMarket]: ...

    def fetch_markets(self, ids: list[str]) -> list[RawMarket]: ...

    def history(
        self,
        *,
        market_id: str,
        series_ticker: str | None,
        token_id: str | None,
        start: datetime,
        end: datetime,
    ) -> list[PricePoint]: ...


@dataclass
class CatalogStats:
    seen: int = 0
    new: int = 0
    rules_changed: int = 0
    watched: int = 0
    queued: int = 0
    errors: int = 0


@dataclass
class SnapshotStats:
    snapshots: int = 0
    missing: int = 0
    settled: int = 0
    rules_changed: int = 0
    errors: int = 0
    failed_venues: list[str] = field(default_factory=list)


@dataclass
class BackfillStats:
    markets: int = 0
    points: int = 0
    errors: int = 0


@dataclass
class RunResult:
    catalog_ran: bool = False
    snapshot_ran: bool = False
    backfill: BackfillStats | None = None


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


class IngestService:
    def __init__(
        self,
        db: Db,
        repo: MarketRepo,
        clock: Clock,
        sources: dict[str, Any],
        *,
        cadence: Cadence,
        min_vol24_usd: float,
        batch_size: int = 500,
        catalog_interval: timedelta = timedelta(minutes=60),
        allowlist: AllowlistRepo | None = None,
    ) -> None:
        self.db = db
        self.repo = repo
        self.clock = clock
        self.sources = sources
        self.cadence = cadence
        self.min_usd = min_vol24_usd
        self.batch_size = batch_size
        self.catalog_interval = catalog_interval
        self.allowlist = allowlist
        self._series_done: set[str] = set()

    # -- helpers -----------------------------------------------------------------------------
    def _log_poll(
        self, source: str, started: float, ok: bool, items: int, err: str | None = None
    ) -> None:
        self.db.conn.execute(
            "insert into poll_log(source, ts, ok, latency_ms, items, err) values (?,?,?,?,?,?)",
            (
                source,
                self.clock.now().isoformat(),
                int(ok),
                int((time.monotonic() - started) * 1000),
                items,
                err,
            ),
        )

    def _backoff_due(self, source: str, base: timedelta, now: datetime) -> bool:
        """Is the next attempt for ``source`` due? Success: after ``base`` since the last attempt.
        Consecutive failures back off exponentially (2, 4, 8 ... minutes, capped at ``base``) so a
        dead venue is not hammered and a healthy one keeps its own schedule."""
        rows = self.db.conn.execute(
            "select ts, ok from poll_log where source=? order by id desc limit 12", (source,)
        ).fetchall()
        if not rows:
            return True
        fails = 0
        for r in rows:
            if r["ok"]:
                break
            fails += 1
        last = _dt(rows[0]["ts"])
        assert last is not None
        interval = base if fails == 0 else min(base, timedelta(minutes=2**fails))
        return now - last >= interval

    def _recent_backfill_failure(self, venue: str, market_id: str, now: datetime) -> bool:
        row = self.db.conn.execute(
            "select ts, ok from poll_log where source=? order by id desc limit 1",
            (f"backfill:{venue}:{market_id}",),
        ).fetchone()
        return bool(row and not row["ok"] and now - (_dt(row["ts"]) or now) < timedelta(hours=1))

    @contextmanager
    def _savepoint(self) -> Iterator[None]:
        c = self.db.conn
        c.execute("savepoint sp")
        try:
            yield
        except BaseException:
            c.execute("rollback to sp")
            c.execute("release sp")
            raise
        else:
            c.execute("release sp")

    def _allow(self) -> AllowList:
        return self.allowlist.snapshot() if self.allowlist else AllowList([])

    def _ingest(
        self, markets: Iterator[RawMarket], stats: CatalogStats, source: Any = None
    ) -> None:
        allow = self._allow()  # one snapshot per pass
        batch: list[RawMarket] = []

        def flush() -> None:
            if not batch:
                return
            with self.db.transaction():
                for m in batch:
                    try:
                        with self._savepoint():
                            tags = tag_market(m)
                            allowed = allow.match(m) is not None
                            res = self.repo.upsert(
                                m,
                                tags,
                                assign_cluster(m),
                                meaningful=is_meaningful(m, self.min_usd),
                                watched=allowed,
                            )
                            if allowed:
                                self.repo.resolve_candidate(m.venue, m.market_id, "accepted")
                            elif is_review_candidate(tags, m, self.min_usd):
                                self.repo.queue_candidate(m, tags)
                                stats.queued += 1
                    except Exception:
                        stats.errors += 1
                        log.exception("upsert failed", extra={"market": m.market_id})
                        continue
                    stats.new += int(res.is_new)
                    stats.rules_changed += int(res.rules_changed)
                    stats.watched += int(res.watched)
            batch.clear()

        for m in markets:
            stats.seen += 1
            batch.append(m)
            if len(batch) >= self.batch_size:
                flush()
        flush()
        # Markets the source skipped as malformed / unidentifiable (never fatal to the pass).
        stats.errors += getattr(source, "parse_errors", 0)

    # -- passes ------------------------------------------------------------------------------
    def catalog_pass(self, venue: str) -> CatalogStats:
        stats = CatalogStats()
        started = time.monotonic()
        try:
            source = self.sources[venue]
            self._ingest(source.iter_markets(), stats, source)
        except Exception as e:
            self._log_poll(f"catalog:{venue}", started, False, stats.seen, str(e))
            raise
        self._log_poll(f"catalog:{venue}", started, True, stats.seen)
        return stats

    def ingest_allowlisted(self, venue: str) -> CatalogStats:
        """Allow-listed markets that the open catalog does not return (closed, settled, or past
        the open listing) are fetched by id so they are stored, watched and settle-tracked."""
        stats = CatalogStats()
        if self.allowlist is None:
            return stats
        ids = self._allow().market_ids(venue)
        have = {
            r[0]
            for r in self.db.conn.execute("select market_id from markets where venue=?", (venue,))
        }
        missing = [i for i in ids if i not in have]
        if not missing:
            return stats
        source = self.sources[venue]
        self._ingest(iter(source.fetch_markets(missing)), stats, source)
        return stats

    def ingest_series(self, venue: str, series_ticker: str) -> CatalogStats:
        """Open, closed and settled events of a series (history for the primary eval source)."""
        stats = CatalogStats()
        source = self.sources[venue]
        for status in SERIES_STATUSES:
            self._ingest(
                source.iter_markets(status=status, series_ticker=series_ticker), stats, source
            )
        self._series_done.add(series_ticker)
        return stats

    def snapshot_pass(self, venues: list[str] | None = None) -> SnapshotStats:
        now = self.clock.now()
        stats = SnapshotStats()
        by_venue: dict[str, list[str]] = {}
        for t in self.repo.watch_targets():
            if venues is None or t.venue in venues:
                by_venue.setdefault(t.venue, []).append(t.market_id)
        started_all = time.monotonic()
        for venue, ids in by_venue.items():
            started = time.monotonic()
            try:
                raws = self.sources[venue].fetch_markets(ids)
            except Exception as e:
                stats.failed_venues.append(venue)
                self._log_poll(f"snapshot:{venue}", started, False, 0, str(e))
                log.exception("snapshot lookup failed", extra={"venue": venue})
                continue
            stats.errors += getattr(self.sources[venue], "parse_errors", 0)
            got = {r.market_id for r in raws}
            stats.missing += len([i for i in ids if i not in got])
            with self.db.transaction():
                for raw in raws:
                    res = self.repo.upsert(raw, None, None, meaningful=None, watched=None)
                    stats.rules_changed += int(res.rules_changed)
                    stats.snapshots += int(self.repo.add_snapshot(raw, now))
                    stats.settled += int(raw.status == "settled")
            self._log_poll(f"snapshot:{venue}", started, True, len(raws))
        self._log_poll("snapshot", started_all, not stats.failed_venues, stats.snapshots)
        return stats

    def backfill_pass(self, max_markets: int = 25) -> BackfillStats:
        """One history backfill per watched market (live ones fill the gap before snapshots)."""
        now = self.clock.now()
        stats = BackfillStats()
        rows = self.db.conn.execute(
            "select m.venue, m.market_id, m.series_ticker, m.status, m.open_time_utc,"
            " m.first_seen_at, m.close_time_utc, t.token_id"
            " from markets m left join market_tokens t"
            "  on t.venue=m.venue and t.market_id=m.market_id and t.outcome='yes'"
            " where m.watched=1 and m.history_through is null"
            " order by m.status in ('settled') , m.venue, m.market_id limit ?",
            (max_markets * 4,),
        ).fetchall()
        for r in rows:
            if self._recent_backfill_failure(r["venue"], r["market_id"], now):
                continue  # failed within the last hour: do not retry every tick
            start = _dt(r["open_time_utc"]) or (_dt(r["first_seen_at"]) or now) - timedelta(days=30)
            end = now
            close = _dt(r["close_time_utc"])
            if r["status"] == "settled" and close is not None:
                end = min(now, close)
            source = self.sources[r["venue"]]
            started = time.monotonic()
            try:
                pts = (
                    []
                    if end <= start
                    else source.history(
                        market_id=r["market_id"],
                        series_ticker=r["series_ticker"],
                        token_id=r["token_id"],
                        start=start,
                        end=end,
                    )
                )
            except Exception as e:
                stats.errors += 1
                self._log_poll(f"backfill:{r['venue']}:{r['market_id']}", started, False, 0, str(e))
                log.exception("history backfill failed", extra={"market": r["market_id"]})
                continue
            with self.db.transaction():
                stats.points += self.repo.add_history(r["venue"], r["market_id"], "yes", pts)
                self.repo.set_history_through(r["venue"], r["market_id"], end)
            stats.markets += 1
            self._log_poll(f"backfill:{r['venue']}:{r['market_id']}", started, True, len(pts))
            if stats.markets + stats.errors >= max_markets:
                break
        return stats

    # -- scheduling --------------------------------------------------------------------------
    def run_due(self) -> RunResult:
        """Per-minute tick; never raises (the scheduler must keep ticking).

        Per venue: catalog hourly, snapshots by the EDGAR-window cadence, each with exponential
        backoff after failures. One venue failing never delays or repeats the other.
        """
        now = self.clock.now()
        res = RunResult()
        for venue in self.sources:
            if not self._backoff_due(f"catalog:{venue}", self.catalog_interval, now):
                continue
            res.catalog_ran = True
            try:
                self.catalog_pass(venue)
            except Exception:
                log.exception("catalog pass failed", extra={"venue": venue})
                continue
            try:
                self.ingest_allowlisted(venue)
            except Exception:
                log.exception("allow-list lookup failed", extra={"venue": venue})
            if venue == "kalshi":
                for series in PRIMARY_SERIES:
                    if series not in self._series_done:
                        try:
                            self.ingest_series("kalshi", series)
                        except Exception:
                            log.exception("series ingest failed", extra={"series": series})
        now = self.clock.now()
        base = self.cadence.interval(now)
        due = [v for v in self.sources if self._backoff_due(f"snapshot:{v}", base, now)]
        if due:
            try:
                self.snapshot_pass(due)
                res.snapshot_ran = True
            except Exception:
                log.exception("snapshot pass failed")
        try:
            res.backfill = self.backfill_pass(max_markets=5)
        except Exception:
            log.exception("backfill pass failed")
        return res
