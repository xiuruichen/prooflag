from __future__ import annotations

from pathlib import Path

from test_repo_cache import T0, Net, cache

from prooflag.clock import FixedClock
from prooflag.linker.repo import AliasRepo
from prooflag.linker.resolve import Alias
from prooflag.store.db import Db


def test_an_alias_can_be_repointed_to_a_new_cik(tmp_path: Path) -> None:
    db = Db(tmp_path / "a.db")
    db.migrate()
    repo = AliasRepo(db, FixedClock(T0))
    assert repo.add(Alias("Facebook", "0000000001", "Wrong", "first guess", "t"))
    assert repo.add(Alias("Facebook", "0001326801", "Meta Platforms", "corrected", "t"))
    assert not repo.add(Alias("Facebook", "0001326801", "Meta Platforms", "again", "t"))
    assert [(a.alias, a.cik) for a in repo.snapshot()] == [("Facebook", "0001326801")]
    db.close()


def test_corrupt_meta_does_not_block_the_offline_fallback(tmp_path: Path) -> None:
    clock = FixedClock(T0)
    cache(tmp_path, Net(), clock).rows()
    meta = tmp_path / "company_tickers.json.meta.json"
    meta.write_text("{}", encoding="utf-8")
    rows, info = cache(tmp_path, Net("down"), clock).rows()
    assert info.source == "stale-cache" and rows
    meta.write_text("not json", encoding="utf-8")
    rows, info = cache(tmp_path, Net("down"), clock).rows()
    assert info.source == "stale-cache" and rows
