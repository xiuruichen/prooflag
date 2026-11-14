from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from fakes import FakeSource, mk

from prooflag.ingest.allowlist import AllowEntry, AllowlistRepo
from prooflag.ingest.models import RawMarket

SEED = Path(__file__).resolve().parent.parent.parent / "config" / "watch_allowlist_seed.json"


def entry(key: str = "A", scope: str = "market", venue: str = "kalshi") -> AllowEntry:
    return AllowEntry(venue, scope, key, "reviewed: settles on a filing", "tester")


def test_allow_revoke_reallow_keeps_full_history(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(FakeSource("kalshi", []))
    repo: AllowlistRepo = env.allowlist
    assert repo.allow(entry())
    assert not repo.allow(entry())  # already active: no duplicate row
    assert len(repo.snapshot()) == 1
    env.clock.advance(timedelta(hours=1))
    assert repo.revoke(entry())
    assert len(repo.snapshot()) == 0
    assert not repo.revoke(entry())
    assert repo.allow(entry())
    assert len(repo.snapshot()) == 1
    rows = env.db.conn.execute("select action from watch_allowlist order by entry_id").fetchall()
    assert [r[0] for r in rows] == ["allow", "revoke", "allow"]  # append-only history


def test_entries_need_reason_and_reviewer_and_valid_scope(make_env) -> None:  # type: ignore[no-untyped-def]
    repo: AllowlistRepo = make_env(FakeSource("kalshi", [])).allowlist
    with pytest.raises(ValueError, match="reason"):
        repo.allow(AllowEntry("kalshi", "market", "A", " ", "tester"))
    with pytest.raises(ValueError, match="reviewer"):
        repo.allow(AllowEntry("kalshi", "market", "A", "why", ""))
    with pytest.raises(ValueError, match="scope"):
        repo.allow(AllowEntry("kalshi", "category", "A", "why", "tester"))


def test_match_by_market_event_or_series_and_venue(make_env) -> None:  # type: ignore[no-untyped-def]
    repo: AllowlistRepo = make_env(FakeSource("kalshi", [])).allowlist
    repo.allow(entry("M1"))
    repo.allow(entry("EV9", scope="event"))
    repo.allow(entry("SER", scope="series"))
    al = repo.snapshot()

    def m(**kw) -> RawMarket:  # type: ignore[no-untyped-def]
        return mk(kw.pop("id", "X"), **kw)

    assert al.match(m(id="M1")) is not None
    assert al.match(m(id="X", event_id="EV9")) is not None
    assert al.match(m(id="X", event_id="E", series_ticker="SER")) is not None
    assert al.match(m(id="X", event_id="E", series_ticker="OTHER")) is None
    assert al.match(m(id="M1", venue="polymarket")) is None  # entries are per venue


def test_catalog_only_watches_allowlisted_markets_and_queues_regex_matches(make_env) -> None:  # type: ignore[no-untyped-def]
    ms = [
        mk("A"),  # allow-listed
        mk("D", vol24_usd_est=3000.0),  # regex-tagged + busy, NOT allow-listed -> review queue
        mk("B", vol24_usd_est=10.0),  # tagged but quiet -> neither
        mk("C", rules_primary="nothing relevant", vol24_usd_est=9000.0),  # untagged
        mk("EO-1", series_ticker="KXEOWEEK", event_id="KXEOWEEK-26NOV14", vol24_usd_est=0.0),
    ]
    env = make_env(FakeSource("kalshi", ms))
    env.allow("kalshi", "A")
    env.allow("kalshi", "KXEOWEEK", scope="series")
    st = env.svc.catalog_pass("kalshi")
    watched = {r[0] for r in env.db.conn.execute("select market_id from markets where watched=1")}
    assert watched == {"A", "EO-1"}
    assert st.watched == 2 and st.queued == 1
    cand = env.db.conn.execute("select * from watch_candidates").fetchall()
    assert [(r["market_id"], r["status"]) for r in cand] == [("D", "pending")]
    assert "fed_register" in cand[0]["tags"]


def test_allowlisting_a_candidate_marks_it_accepted_and_revoking_unwatches(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(FakeSource("kalshi", [mk("D", vol24_usd_est=3000.0)]))
    env.svc.catalog_pass("kalshi")
    assert env.one("select status from watch_candidates")[0] == "pending"
    assert env.one("select watched from markets")[0] == 0
    env.allow("kalshi", "D")
    env.svc.catalog_pass("kalshi")
    assert env.one("select status from watch_candidates")[0] == "accepted"
    assert env.one("select watched from markets")[0] == 1
    env.allowlist.revoke(entry("D"))
    env.svc.catalog_pass("kalshi")
    assert env.one("select watched from markets")[0] == 0  # the allow-list, not volume, decides


def test_watch_does_not_depend_on_volume(make_env) -> None:  # type: ignore[no-untyped-def]
    src = FakeSource("kalshi", [mk("A", vol24_usd_est=5000.0)])
    env = make_env(src)
    env.allow("kalshi", "A")
    env.svc.catalog_pass("kalshi")
    src.catalog = [mk("A", vol24_usd_est=0.0)]
    env.svc.catalog_pass("kalshi")
    assert env.one("select watched, meaningful from markets")[:] == (1, 0)


def test_allowlisted_markets_missing_from_the_open_catalog_are_fetched_by_id(make_env) -> None:  # type: ignore[no-untyped-def]
    settled = mk("OLD", status="settled", result="no", vol24_usd_est=0.0)
    src = FakeSource("kalshi", [])  # the open catalog does not return it
    src.lookups["OLD"] = settled
    env = make_env(src)
    env.allow("kalshi", "OLD")
    st = env.svc.ingest_allowlisted("kalshi")
    assert st.new == 1 and src.lookup_calls == [["OLD"]]
    row = env.one("select status, result, watched from markets")
    assert tuple(row) == ("settled", "no", 1)
    assert env.svc.ingest_allowlisted("kalshi").new == 0  # present now: no refetch
    assert len(src.lookup_calls) == 1


def test_seed_file_is_well_formed_and_contains_required_entries() -> None:
    data = json.loads(SEED.read_text(encoding="utf-8"))
    entries = data["entries"]
    keys = [(e["venue"], e["scope"], e["key"]) for e in entries]
    assert len(keys) == len(set(keys))  # no duplicates
    assert all(e["reason"].strip() and e["reviewer"].strip() for e in entries)
    assert all(e["scope"] in ("market", "event", "series") for e in entries)
    assert ("kalshi", "series", "KXEOWEEK") in keys
    strat = json.loads(
        (SEED.parent.parent / "fixtures/strategy_2026_05/polymarket_market_may31.json").read_text(
            encoding="utf-8"
        )
    )
    assert ("polymarket", "market", strat["conditionId"]) in keys
    assert not any(k[2].startswith("KXEOWEEK-") for k in keys)  # covered by the series entry
    assert "@" not in SEED.read_text(encoding="utf-8")  # no personal contact data


def test_seed_loading_is_idempotent(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(FakeSource("kalshi", []))
    n = env.allowlist.seed_from_file(SEED)
    assert n == len(json.loads(SEED.read_text(encoding="utf-8"))["entries"])
    assert env.allowlist.seed_from_file(SEED) == 0
    assert len(env.allowlist.snapshot()) == n
    src = env.db.conn.execute("select distinct source from watch_allowlist").fetchall()
    assert [r[0] for r in src] == [SEED.name]
