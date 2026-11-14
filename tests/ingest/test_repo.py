from __future__ import annotations

import copy
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from prooflag.clock import FixedClock
from prooflag.ingest.models import PricePoint, RawMarket
from prooflag.ingest.repo import MarketRepo, rules_sha
from prooflag.ingest.tagging import Tag, assign_cluster, tag_market
from prooflag.store.db import Db
from prooflag.store.locker import Locker

T0 = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[tuple[Db, MarketRepo, FixedClock, Locker]]:
    db = Db(tmp_path / "r.db")
    db.migrate()
    clock = FixedClock(T0)
    locker = Locker(tmp_path / "locker", db)
    yield db, MarketRepo(db, locker, clock), clock, locker
    db.close()


def kalshi_market(**kw) -> RawMarket:  # type: ignore[no-untyped-def]
    base = dict(
        venue="kalshi",
        market_id="KXEOWEEK-26NOV14-3",
        title="More than 3 EOs?",
        rules_primary="Counts EOs per the Federal Register.",
        rules_secondary="Signing date.",
        event_id="KXEOWEEK-26NOV14",
        event_title="EOs this week",
        series_ticker="KXEOWEEK",
        category="Politics",
        status="open",
        yes_bid=0.1,
        yes_ask=0.12,
        last_price=0.11,
        vol24_contracts=5000.0,
        vol24_usd_est=550.0,
        open_interest_contracts=9000.0,
        close_time=T0 + timedelta(days=1),
        open_time=T0 - timedelta(days=5),
        raw={"a": 1},
    )
    base.update(kw)
    return RawMarket(**base)


def up(repo: MarketRepo, m: RawMarket, **kw):  # type: ignore[no-untyped-def]
    tags = kw.pop("tags", tag_market(m))
    return repo.upsert(
        m,
        tags,
        assign_cluster(m),
        meaningful=kw.pop("meaningful", False),
        watched=kw.pop("watch", True),
    )


def one(db: Db, sql: str, *args):  # type: ignore[no-untyped-def]
    return db.conn.execute(sql, args).fetchone()


def test_rules_sha_covers_title_and_both_rule_fields_exactly() -> None:
    sha = rules_sha("T", "P", "S")
    assert sha == hashlib.sha256(b"T\x1fP\x1fS").hexdigest()
    assert rules_sha("T2", "P", "S") != sha  # title is versioned
    assert rules_sha("T", "P ", "S") != sha  # exact text: whitespace is not normalized
    assert rules_sha("T", "P", "S") == sha


def test_new_market_rows_versions_tags_cluster_and_units(env) -> None:  # type: ignore[no-untyped-def]
    db, repo, _clock, locker = env
    m = kalshi_market()
    res = up(repo, m, meaningful=False)
    assert res.is_new and not res.rules_changed and res.watched
    row = one(db, "select * from markets")
    assert row["current_rules_sha"] == res.rules_sha
    assert row["vol24_contracts"] == 5000.0 and row["vol24_usd_est"] == 550.0
    assert row["open_interest_contracts"] == 9000.0 and row["liquidity_usd"] is None
    assert row["series_ticker"] == "KXEOWEEK" and row["cluster_id"] == "weekly_eo:2026-11-14"
    assert row["meaningful"] == 0 and row["watched"] == 1
    assert "rules_text" not in row.keys()  # noqa: SIM118  (sqlite3.Row: `in` tests values)
    v = one(db, "select * from market_versions")
    assert (v["rules_text"], v["rules_secondary"], v["title"]) == (
        m.rules_primary,
        m.rules_secondary,
        m.title,
    )
    tags = {r[0] for r in db.conn.execute("select tag from market_tags")}
    assert {"weekly_eo", "primary_eval", "fed_register"} <= tags
    span = one(db, "select matched_span from market_tags where tag='fed_register'")[0]
    assert span in m.rules_primary
    assert (
        one(db, "select count(*) from market_clusters where cluster_id='weekly_eo:2026-11-14'")[0]
        == 1
    )
    assert row["raw_json_sha"] and locker.get(row["raw_json_sha"])


def test_polymarket_liquidity_is_stored_apart_from_open_interest(env) -> None:  # type: ignore[no-untyped-def]
    db, repo, *_ = env
    m = RawMarket(
        venue="polymarket",
        market_id="0xabc",
        title="t",
        rules_primary="r",
        vol24_usd_est=2000.0,
        liquidity_usd=777000.0,
        token_ids={"yes": "111", "no": "222"},
    )
    up(repo, m, tags=[Tag("sec", "x", "r")])
    row = one(db, "select * from markets")
    assert row["liquidity_usd"] == 777000.0 and row["open_interest_contracts"] is None
    assert {
        (r[0], r[1]) for r in db.conn.execute("select outcome, token_id from market_tokens")
    } == {("yes", "111"), ("no", "222")}


def test_unchanged_rules_do_not_add_versions_or_reupload_raw(env) -> None:  # type: ignore[no-untyped-def]
    db, repo, _c, _l = env
    up(repo, kalshi_market(raw={"a": 1}))
    m2 = kalshi_market(raw={"a": 2}, last_price=0.5, vol24_usd_est=9999.0)
    res = up(repo, m2)
    assert not res.is_new and not res.rules_changed
    assert one(db, "select count(*) from market_versions")[0] == 1
    assert one(db, "select count(*) from artifacts where kind='market_raw'")[0] == 1
    assert one(db, "select vol24_usd_est from markets")[0] == 9999.0  # live columns do update


def test_rule_edit_is_detected_and_logged(env) -> None:  # type: ignore[no-untyped-def]
    db, repo, clock, _l = env
    a = up(repo, kalshi_market())
    clock.advance(timedelta(hours=1))
    b = up(
        repo,
        kalshi_market(
            rules_primary="Counts EOs by PUBLICATION date.",
            raw={"a": 1, "rules_primary": "Counts EOs by PUBLICATION date."},
        ),
    )
    assert b.rules_changed and b.previous_sha == a.rules_sha and b.rules_sha != a.rules_sha
    ch = one(db, "select * from market_rule_changes")
    assert (ch["from_sha"], ch["to_sha"]) == (a.rules_sha, b.rules_sha)
    assert (
        one(db, "select count(*) from artifacts where kind='market_raw'")[0] == 2
    )  # re-stored on edit


def test_title_only_edit_is_a_rule_change(env) -> None:  # type: ignore[no-untyped-def]
    _db, repo, *_ = env
    up(repo, kalshi_market())
    assert up(repo, kalshi_market(title="Different title")).rules_changed


def test_revert_a_b_a_is_visible_in_the_change_log(env) -> None:  # type: ignore[no-untyped-def]
    db, repo, clock, _l = env
    a = up(repo, kalshi_market())
    clock.advance(timedelta(minutes=5))
    b = up(repo, kalshi_market(rules_secondary="Edited."))
    clock.advance(timedelta(minutes=5))
    a2 = up(repo, kalshi_market())  # back to the original text
    assert a2.rules_changed and a2.rules_sha == a.rules_sha and a2.previous_sha == b.rules_sha
    changes = [
        (r["from_sha"], r["to_sha"])
        for r in db.conn.execute("select * from market_rule_changes order by change_id")
    ]
    assert changes == [(a.rules_sha, b.rules_sha), (b.rules_sha, a.rules_sha)]
    assert one(db, "select count(*) from market_versions")[0] == 2  # texts stored once each
    assert one(db, "select current_rules_sha from markets")[0] == a.rules_sha


def test_watched_follows_the_flag_not_volume_and_none_keeps_it(env) -> None:  # type: ignore[no-untyped-def]
    db, repo, *_ = env
    up(repo, kalshi_market(), watch=True, meaningful=True)
    up(repo, kalshi_market(vol24_usd_est=0.0), watch=True, meaningful=False)  # volume dipped
    assert one(db, "select watched, meaningful from markets")[:] == (1, 0)
    repo.upsert(kalshi_market(), None, None, meaningful=None, watched=None)  # lookup: keep
    assert one(db, "select watched from markets")[0] == 1
    up(repo, kalshi_market(), watch=False)  # allow-list entry revoked
    assert one(db, "select watched from markets")[0] == 0


def test_lookup_without_event_context_does_not_erase_known_fields(env) -> None:  # type: ignore[no-untyped-def]
    db, repo, *_ = env
    up(repo, kalshi_market())
    bare = kalshi_market(
        series_ticker=None, event_title=None, category=None, event_id=None, open_time=None
    )
    up(repo, bare, meaningful=None)  # type: ignore[arg-type]
    row = one(db, "select * from markets")
    assert (row["series_ticker"], row["event_title"], row["category"]) == (
        "KXEOWEEK",
        "EOs this week",
        "Politics",
    )
    assert row["meaningful"] == 0 and row["open_time_utc"]


def test_tags_are_synced_not_accumulated(env) -> None:  # type: ignore[no-untyped-def]
    db, repo, *_ = env
    m = kalshi_market()
    up(repo, m, tags=[Tag("sec", "r", "x"), Tag("court", "r", "y")])
    up(repo, m, tags=[Tag("sec", "r", "x")])
    assert {r[0] for r in db.conn.execute("select tag from market_tags")} == {"sec"}


def test_untagged_market_stores_no_raw_blob(env) -> None:  # type: ignore[no-untyped-def]
    db, repo, *_ = env
    up(repo, kalshi_market(), tags=[], watch=False)
    assert one(db, "select count(*) from artifacts")[0] == 0
    assert one(db, "select raw_json_sha from markets")[0] is None


def test_settlement_status_result_and_settled_at_once(env) -> None:  # type: ignore[no-untyped-def]
    db, repo, clock, _l = env
    up(repo, kalshi_market())
    clock.advance(timedelta(hours=2))
    up(repo, kalshi_market(status="settled", result="no"))
    row = one(db, "select status, result, settled_at from markets")
    assert tuple(row) == ("settled", "no", (T0 + timedelta(hours=2)).isoformat())
    clock.advance(timedelta(hours=5))
    up(repo, kalshi_market(status="settled", result=None))  # a later lookup lacking result
    row = one(db, "select status, result, settled_at from markets")
    assert tuple(row) == ("settled", "no", (T0 + timedelta(hours=2)).isoformat())


def test_batch_is_atomic(env) -> None:  # type: ignore[no-untyped-def]
    db, repo, *_ = env
    with pytest.raises(RuntimeError), db.transaction():
        up(repo, kalshi_market())
        raise RuntimeError("boom")
    assert one(db, "select count(*) from markets")[0] == 0
    assert one(db, "select count(*) from market_versions")[0] == 0


def test_snapshots_store_bid_ask_last_and_dedupe_on_timestamp(env) -> None:  # type: ignore[no-untyped-def]
    db, repo, *_ = env
    m = kalshi_market()
    up(repo, m)
    assert repo.add_snapshot(m, T0)
    assert not repo.add_snapshot(
        kalshi_market(last_price=0.99), T0
    )  # same ts: ignored, not replaced
    row = one(db, "select * from price_snapshots")
    assert (row["yes_bid"], row["yes_ask"], row["last_price"]) == (0.1, 0.12, 0.11)
    assert row["volume"] == 550.0 and row["open_interest"] == 9000.0 and row["source"] == "snapshot"


def test_history_rows_have_no_volume_unit_confusion(env) -> None:  # type: ignore[no-untyped-def]
    db, repo, *_ = env
    m = kalshi_market()
    up(repo, m)
    pts = [
        PricePoint(
            ts=T0 - timedelta(hours=h),
            price=None if h == 1 else 0.2,
            yes_bid=0.1,
            yes_ask=0.3,
            volume=12.0,
            open_interest=50.0,
        )
        for h in (1, 2, 3)
    ]
    assert repo.add_history("kalshi", m.market_id, "yes", pts) == 3
    assert repo.add_history("kalshi", m.market_id, "yes", pts) == 0  # idempotent
    rows = db.conn.execute("select * from price_snapshots where source='history'").fetchall()
    assert len(rows) == 3 and all(r["volume"] is None for r in rows)  # candle volume is per-period
    assert sum(r["last_price"] is None for r in rows) == 1  # null trade price kept as NULL


def test_watch_targets_follow_status_and_exclude_settled(env) -> None:  # type: ignore[no-untyped-def]
    _db, repo, *_ = env
    up(repo, kalshi_market(market_id="A", event_id="E1"))
    up(repo, kalshi_market(market_id="B", event_id="E2", status="past_end"))
    up(repo, kalshi_market(market_id="C", event_id="E3", status="settled", result="yes"))
    up(repo, kalshi_market(market_id="D", event_id="E4"), watch=False)
    got = {(t.venue, t.market_id) for t in repo.watch_targets()}
    assert got == {("kalshi", "A"), ("kalshi", "B")}  # settled and never-watched excluded


def test_deepcopy_of_raw_is_not_mutated_by_upsert(env) -> None:  # type: ignore[no-untyped-def]
    _db, repo, *_ = env
    m = kalshi_market(raw={"nested": {"k": [1, 2]}})
    before = copy.deepcopy(m.raw)
    up(repo, m)
    assert m.raw == before


def test_lookup_update_keeps_tags_and_cluster_but_still_detects_rule_edits(env) -> None:  # type: ignore[no-untyped-def]
    db, repo, _c, _l = env
    m = kalshi_market()
    up(repo, m)
    tags_before = {r[0] for r in db.conn.execute("select tag from market_tags")}
    lookup = kalshi_market(
        series_ticker=None,
        event_title=None,
        event_id=None,
        category=None,
        rules_primary="Edited rules.",
        status="settled",
        result="yes",
        raw={"lookup": True},
    )
    res = repo.upsert(lookup, None, None, meaningful=None, watched=None)
    assert res.rules_changed and res.watched
    assert {r[0] for r in db.conn.execute("select tag from market_tags")} == tags_before
    row = one(db, "select cluster_id, status, result from markets")
    assert tuple(row) == ("weekly_eo:2026-11-14", "settled", "yes")
    assert (
        one(db, "select count(*) from artifacts where kind='market_raw'")[0] == 2
    )  # tagged: raw re-stored
