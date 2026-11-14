"""Persistence for ingested markets: versioned rules, tags, clusters, snapshots, history.

Callers batch writes inside ``Db.transaction()``; nothing here opens its own transaction.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from prooflag.clock import Clock
from prooflag.ingest.models import LIVE_STATUSES, PricePoint, RawMarket
from prooflag.ingest.tagging import Cluster, Tag
from prooflag.store.db import Db
from prooflag.store.locker import Locker

_SEP = "\x1f"


def rules_sha(title: str, rules_primary: str, rules_secondary: str) -> str:
    """Hash of the exact stored rule text (spans are verified against it) plus the title."""
    return hashlib.sha256(_SEP.join([title, rules_primary, rules_secondary]).encode()).hexdigest()


@dataclass(frozen=True)
class UpsertResult:
    is_new: bool
    rules_changed: bool
    rules_sha: str
    previous_sha: str | None
    watched: bool


@dataclass(frozen=True)
class WatchTarget:
    venue: str
    market_id: str
    series_ticker: str | None
    status: str


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


class MarketRepo:
    def __init__(self, db: Db, locker: Locker, clock: Clock) -> None:
        self.db = db
        self.locker = locker
        self.clock = clock

    # -- markets -----------------------------------------------------------------------------
    def upsert(
        self,
        m: RawMarket,
        tags: list[Tag] | None,
        cluster: Cluster | None,
        *,
        meaningful: bool | None,
        watched: bool | None,
    ) -> UpsertResult:
        """Insert or update. ``tags``/``cluster`` of None mean "keep what is stored" (used by
        lookups that carry no event context, e.g. snapshot refreshes). ``watched`` is decided by
        the allow-list (not by volume); None keeps the stored value."""
        c = self.db.conn
        now = self.clock.now()
        sha = rules_sha(m.title, m.rules_primary, m.rules_secondary)
        prev = c.execute(
            "select current_rules_sha, raw_json_sha, settled_at from markets"
            " where venue=? and market_id=?",
            (m.venue, m.market_id),
        ).fetchone()
        is_new = prev is None
        previous_sha = None if prev is None else prev["current_rules_sha"]
        rules_changed = previous_sha is not None and previous_sha != sha

        cluster_id = None if cluster is None else cluster.cluster_id
        if cluster is not None:
            c.execute(
                "insert or ignore into market_clusters(cluster_id, label, rule, created_at)"
                " values (?,?,?,?)",
                (cluster.cluster_id, cluster.label, cluster.rule, now.isoformat()),
            )
        c.execute(
            "insert into markets(venue, market_id, cluster_id, title, resolution_source,"
            " close_time_utc, status, first_seen_at, last_seen_at, series_ticker, event_id,"
            " event_title, category, open_time_utc, vol24_contracts, vol24_usd_est,"
            " open_interest_contracts, liquidity_usd, meaningful, watched, current_rules_sha,"
            " result, settled_at, yes_label)"
            " values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " on conflict(venue, market_id) do update set"
            " cluster_id=coalesce(excluded.cluster_id, markets.cluster_id), title=excluded.title,"
            " resolution_source=excluded.resolution_source,"
            " close_time_utc=coalesce(excluded.close_time_utc, markets.close_time_utc),"
            " status=excluded.status, last_seen_at=excluded.last_seen_at,"
            " series_ticker=coalesce(excluded.series_ticker, markets.series_ticker),"
            " event_id=coalesce(excluded.event_id, markets.event_id),"
            " event_title=coalesce(excluded.event_title, markets.event_title),"
            " category=coalesce(excluded.category, markets.category),"
            " open_time_utc=coalesce(excluded.open_time_utc, markets.open_time_utc),"
            " vol24_contracts=coalesce(excluded.vol24_contracts, markets.vol24_contracts),"
            " vol24_usd_est=coalesce(excluded.vol24_usd_est, markets.vol24_usd_est),"
            " open_interest_contracts=coalesce(excluded.open_interest_contracts,"
            "   markets.open_interest_contracts),"
            " liquidity_usd=coalesce(excluded.liquidity_usd, markets.liquidity_usd),"
            " meaningful=case when ? is null then markets.meaningful else excluded.meaningful end,"
            " watched=case when ? is null then markets.watched else excluded.watched end,"
            " current_rules_sha=excluded.current_rules_sha,"
            " result=coalesce(excluded.result, markets.result),"
            " settled_at=coalesce(markets.settled_at, excluded.settled_at),"
            " yes_label=coalesce(excluded.yes_label, markets.yes_label)",
            (
                m.venue,
                m.market_id,
                cluster_id,
                m.title,
                m.resolution_source,
                _iso(m.close_time),
                m.status,
                now.isoformat(),
                now.isoformat(),
                m.series_ticker,
                m.event_id,
                m.event_title,
                m.category,
                _iso(m.open_time),
                m.vol24_contracts,
                m.vol24_usd_est,
                m.open_interest_contracts,
                m.liquidity_usd,
                int(bool(meaningful)),
                int(bool(watched)),
                sha,
                m.result,
                now.isoformat() if m.status == "settled" else None,
                m.yes_label,
                None if meaningful is None else int(meaningful),
                None if watched is None else int(watched),
            ),
        )
        c.execute(
            "insert or ignore into market_versions(venue, market_id, rules_sha, rules_text,"
            " seen_at, title, rules_secondary) values (?,?,?,?,?,?,?)",
            (
                m.venue,
                m.market_id,
                sha,
                m.rules_primary,
                now.isoformat(),
                m.title,
                m.rules_secondary,
            ),
        )
        if rules_changed and previous_sha is not None:
            c.execute(
                "insert into market_rule_changes(venue, market_id, from_sha, to_sha, seen_at)"
                " values (?,?,?,?,?)",
                (m.venue, m.market_id, previous_sha, sha, now.isoformat()),
            )

        if tags is not None:
            wanted = {t.tag for t in tags}
            have = {
                r[0]
                for r in c.execute(
                    "select tag from market_tags where venue=? and market_id=?",
                    (m.venue, m.market_id),
                )
            }
            for stale in have - wanted:
                c.execute(
                    "delete from market_tags where venue=? and market_id=? and tag=?",
                    (m.venue, m.market_id, stale),
                )
            for t in tags:
                c.execute(
                    "insert or replace into market_tags(venue, market_id, tag, reason,"
                    " matched_span) values (?,?,?,?,?)",
                    (m.venue, m.market_id, t.tag, t.reason, t.span),
                )
        for outcome, token in m.token_ids.items():
            c.execute(
                "insert or ignore into market_tokens(venue, market_id, outcome, token_id)"
                " values (?,?,?,?)",
                (m.venue, m.market_id, outcome, token),
            )

        raw_sha = None if prev is None else prev["raw_json_sha"]
        tagged = (
            bool(tags)
            if tags is not None
            else bool(
                c.execute(
                    "select 1 from market_tags where venue=? and market_id=? limit 1",
                    (m.venue, m.market_id),
                ).fetchone()
            )
        )
        if tagged and (is_new or rules_changed or raw_sha is None):
            blob = json.dumps(m.raw, sort_keys=True, default=str).encode()
            raw_sha = self.locker.put(
                blob, kind="market_raw", source_url=f"{m.venue}:{m.market_id}", fetched_at=now
            )
            c.execute(
                "update markets set raw_json_sha=? where venue=? and market_id=?",
                (raw_sha, m.venue, m.market_id),
            )
        watched = bool(
            c.execute(
                "select watched from markets where venue=? and market_id=?",
                (m.venue, m.market_id),
            ).fetchone()[0]
        )
        return UpsertResult(is_new, rules_changed, sha, previous_sha, watched)

    # -- candidate review queue ----------------------------------------------------------------
    def queue_candidate(self, m: RawMarket, tags: list[Tag]) -> None:
        """Regex matches wait here for review; they are never auto-watched."""
        now = self.clock.now().isoformat()
        names = ",".join(sorted(t.tag for t in tags))
        self.db.conn.execute(
            "insert into watch_candidates(venue, market_id, title, tags, vol24_usd_est,"
            " first_seen_at, last_seen_at) values (?,?,?,?,?,?,?)"
            " on conflict(venue, market_id) do update set tags=excluded.tags,"
            " vol24_usd_est=coalesce(excluded.vol24_usd_est, watch_candidates.vol24_usd_est),"
            " last_seen_at=excluded.last_seen_at, title=excluded.title",
            (m.venue, m.market_id, m.title, names, m.vol24_usd_est, now, now),
        )

    def resolve_candidate(self, venue: str, market_id: str, status: str) -> None:
        self.db.conn.execute(
            "update watch_candidates set status=? where venue=? and market_id=?"
            " and status='pending'",
            (status, venue, market_id),
        )

    def watch_targets(self) -> list[WatchTarget]:
        marks = ",".join("?" * len(LIVE_STATUSES))
        rows = self.db.conn.execute(
            f"select venue, market_id, series_ticker, status from markets"
            f" where watched=1 and status in ({marks}) order by venue, market_id",
            LIVE_STATUSES,
        ).fetchall()
        return [WatchTarget(r[0], r[1], r[2], r[3]) for r in rows]

    # -- prices ------------------------------------------------------------------------------
    def add_snapshot(self, m: RawMarket, ts: datetime, source: str = "snapshot") -> bool:
        """Latest quote. ``volume`` is the 24h USD estimate (comparable across venues),
        ``open_interest`` is Kalshi contracts. Existing rows are never replaced."""
        cur = self.db.conn.execute(
            "insert or ignore into price_snapshots(venue, market_id, outcome, ts_utc, price,"
            " volume, open_interest, source, yes_bid, yes_ask, last_price)"
            " values (?,?,?,?,?,?,?,?,?,?,?)",
            (
                m.venue,
                m.market_id,
                "yes",
                ts.isoformat(),
                m.last_price,
                m.vol24_usd_est,
                m.open_interest_contracts,
                source,
                m.yes_bid,
                m.yes_ask,
                m.last_price,
            ),
        )
        return cur.rowcount == 1

    def add_history(self, venue: str, market_id: str, outcome: str, pts: list[PricePoint]) -> int:
        """Historical candles/points. ``volume`` stays NULL: candle volume is per-period contracts
        and not comparable with the snapshot 24h USD estimate."""
        n = 0
        for p in pts:
            cur = self.db.conn.execute(
                "insert or ignore into price_snapshots(venue, market_id, outcome, ts_utc, price,"
                " volume, open_interest, source, yes_bid, yes_ask, last_price)"
                " values (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    venue,
                    market_id,
                    outcome,
                    p.ts.isoformat(),
                    p.price,
                    None,
                    p.open_interest,
                    "history",
                    p.yes_bid,
                    p.yes_ask,
                    p.price,
                ),
            )
            n += cur.rowcount
        return n

    def set_history_through(self, venue: str, market_id: str, ts: datetime) -> None:
        self.db.conn.execute(
            "update markets set history_through=? where venue=? and market_id=?",
            (ts.isoformat(), venue, market_id),
        )
