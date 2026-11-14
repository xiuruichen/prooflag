from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from prooflag.clock import FixedClock
from prooflag.linker.cache import SecTickerCache
from prooflag.linker.index import TickerIndex
from prooflag.linker.repo import AliasRepo, EntityRepo
from prooflag.linker.resolve import Alias, EntityLinker
from prooflag.sec_client import SecClient
from prooflag.store.db import Db

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "sec"
BODY = (FIX / "company_tickers_subset.json").read_bytes()
LAST_MOD = json.loads((FIX / "company_tickers_meta.json").read_text())["last_modified"]
T0 = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


@pytest.fixture
def db(tmp_path: Path) -> Db:
    d = Db(tmp_path / "l.db")
    d.migrate()
    return d


# -- entities and the review queue -------------------------------------------------------------
def test_record_resolved_ambiguous_and_unresolved_and_list_the_review_queue(db: Db) -> None:
    rows = list(json.loads(BODY).values())
    linker = EntityLinker(TickerIndex.from_rows(rows), [])
    repo = EntityRepo(db, FixedClock(T0))
    for q in ("NVDA", "Rio Tinto", "OpenAI", "Nvidia Corporatoin"):
        repo.record(linker.resolve(q))
    got = {r["query"]: r for r in db.conn.execute("select * from entities")}
    assert got["NVDA"]["link_status"] == "resolved" and got["NVDA"]["cik"] == "0001045810"
    assert got["NVDA"]["ticker"] == "NVDA" and got["NVDA"]["link_method"] == "ticker"
    assert got["Rio Tinto"]["link_status"] == "ambiguous" and got["Rio Tinto"]["cik"] is None
    assert len(json.loads(got["Rio Tinto"]["candidates_json"])) == 2
    queue = {r["query"] for r in repo.review_queue()}
    assert queue == {"Rio Tinto", "OpenAI", "Nvidia Corporatoin"}  # never the resolved one


def test_recording_the_same_query_updates_instead_of_duplicating(db: Db) -> None:
    rows = list(json.loads(BODY).values())
    index = TickerIndex.from_rows(rows)
    repo = EntityRepo(db, FixedClock(T0))
    repo.record(EntityLinker(index, []).resolve("MicroStrategy"))  # unresolved
    assert [r["query"] for r in repo.review_queue()] == ["MicroStrategy"]
    alias = Alias("MicroStrategy", "0001050446", "Strategy Inc", "former name", "tester")
    repo.record(EntityLinker(index, [alias]).resolve("MicroStrategy"))  # now resolved
    assert db.conn.execute("select count(*) from entities").fetchone()[0] == 1
    assert repo.review_queue() == []


# -- reviewed aliases (append-only) -------------------------------------------------------------
def test_alias_add_revoke_history_and_snapshot(db: Db) -> None:
    repo = AliasRepo(db, FixedClock(T0))
    a = Alias("MicroStrategy", "0001050446", "Strategy Inc", "former name", "tester")
    assert repo.add(a) and not repo.add(a)  # second add is a no-op
    assert [x.alias for x in repo.snapshot()] == ["MicroStrategy"]
    assert repo.revoke(a)
    assert repo.snapshot() == []
    assert repo.add(a)
    acts = [r[0] for r in db.conn.execute("select action from entity_aliases order by alias_id")]
    assert acts == ["allow", "revoke", "allow"]
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.conn.execute("update entity_aliases set cik='x'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.conn.execute("delete from entity_aliases")


def test_alias_seed_file_loads_and_is_idempotent(db: Db) -> None:
    seed = Path(__file__).resolve().parent.parent.parent / "config" / "entity_aliases.json"
    repo = AliasRepo(db, FixedClock(T0))
    n = repo.seed_from_file(seed)
    assert n >= 1 and repo.seed_from_file(seed) == 0
    assert any(a.alias == "MicroStrategy" and a.cik == "0001050446" for a in repo.snapshot())
    assert "@" not in seed.read_text(encoding="utf-8")


# -- ticker file cache --------------------------------------------------------------------------
class Net:
    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode
        self.requests: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if self.mode == "down":
            raise httpx.ConnectError("down")
        if self.mode == "403":
            return httpx.Response(403)
        if self.mode == "304" and req.headers.get("if-modified-since") == LAST_MOD:
            return httpx.Response(304)
        return httpx.Response(200, content=BODY, headers={"Last-Modified": LAST_MOD})


def cache(tmp_path: Path, net: Net, clock: FixedClock, max_age_h: int = 24) -> SecTickerCache:
    c = SecClient(
        user_agent="Prooflag t@example.org",
        max_rps=100.0,
        transport=httpx.MockTransport(net),
        sleep=lambda _s: None,
    )
    return SecTickerCache(
        tmp_path / "company_tickers.json", c, clock, max_age=timedelta(hours=max_age_h)
    )


def test_first_load_fetches_and_stores_body_and_last_modified(tmp_path: Path) -> None:
    net, clock = Net(), FixedClock(T0)
    rows, info = cache(tmp_path, net, clock).rows()
    assert info.source == "network" and len(rows) == len(json.loads(BODY))
    assert info.last_modified == LAST_MOD and (tmp_path / "company_tickers.json").exists()
    assert net.requests[0].headers["user-agent"] == "Prooflag t@example.org"


def test_fresh_cache_makes_no_request(tmp_path: Path) -> None:
    clock = FixedClock(T0)
    cache(tmp_path, Net(), clock).rows()
    net2 = Net()
    clock.advance(timedelta(hours=3))
    _rows, info = cache(tmp_path, net2, clock).rows()
    assert info.source == "cache" and net2.requests == []


def test_stale_cache_revalidates_with_if_modified_since_and_keeps_the_body(tmp_path: Path) -> None:
    clock = FixedClock(T0)
    cache(tmp_path, Net(), clock).rows()
    clock.advance(timedelta(hours=30))
    net2 = Net("304")
    _rows, info = cache(tmp_path, net2, clock).rows()
    assert info.source == "cache-revalidated"
    assert net2.requests[0].headers["if-modified-since"] == LAST_MOD
    # revalidation resets the age: the next load within max_age needs no request
    net3 = Net()
    _rows, info = cache(tmp_path, net3, clock).rows()
    assert info.source == "cache" and net3.requests == []


def test_stale_cache_is_used_when_the_network_fails(tmp_path: Path) -> None:
    clock = FixedClock(T0)
    cache(tmp_path, Net(), clock).rows()
    clock.advance(timedelta(days=5))
    rows, info = cache(tmp_path, Net("down"), clock).rows()
    assert info.source == "stale-cache" and rows
    rows, info = cache(tmp_path, Net("403"), clock).rows()  # access refused: still usable
    assert info.source == "stale-cache"


def test_no_cache_and_network_failure_raises(tmp_path: Path) -> None:
    with pytest.raises(Exception, match=r"company_tickers|down|SEC"):
        cache(tmp_path, Net("down"), FixedClock(T0)).rows()


def test_corrupt_cache_is_refetched(tmp_path: Path) -> None:
    clock = FixedClock(T0)
    cache(tmp_path, Net(), clock).rows()
    (tmp_path / "company_tickers.json").write_text("{not json", encoding="utf-8")
    net = Net()
    rows, info = cache(tmp_path, net, clock).rows()
    assert info.source == "network" and rows and len(net.requests) == 1
