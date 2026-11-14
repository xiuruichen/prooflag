from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from prooflag.clock import FixedClock
from prooflag.config import Settings
from prooflag.store.db import Db
from prooflag.watchers.factory import build_sec_service

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "sec"
SUB = json.loads((FIX / "submissions_anthropic.json").read_text(encoding="utf-8"))


def test_factory_seeds_the_watch_list_and_uses_the_sec_only_contact(tmp_path: Path) -> None:
    s = Settings(contact_email="real.person@example.org", data_dir=tmp_path, _env_file=None)
    db = Db(s.db_path)
    db.migrate()
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if "submissions" in str(req.url):
            cik = str(req.url).rsplit("CIK", 1)[1].split(".")[0]
            d = copy.deepcopy(SUB)
            d["cik"] = int(cik)
            rec = d["filings"]["recent"]
            rec["accessionNumber"] = [f"{a}-{cik[-4:]}" for a in rec["accessionNumber"]]
            return httpx.Response(200, json=d)
        return httpx.Response(200, text="<feed xmlns='http://www.w3.org/2005/Atom'></feed>")

    svc = build_sec_service(
        s,
        db,
        FixedClock(datetime(2026, 11, 16, 15, tzinfo=UTC)),
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,
    )
    res = svc.run_due()
    assert res.polled_ciks == 2 and res.polled_atom == len(s.atom_forms) == 5
    assert res.new_filings == [] and res.errors == 0  # first poll is a baseline
    assert {r.headers["user-agent"] for r in seen} == {"Prooflag real.person@example.org"}
    assert all(r.url.host in ("data.sec.gov", "www.sec.gov") for r in seen)
    db.close()


def test_factory_refuses_a_placeholder_contact(tmp_path: Path) -> None:
    s = Settings(contact_email="you@example.com", data_dir=tmp_path, _env_file=None)
    db = Db(s.db_path)
    db.migrate()
    with pytest.raises(ValueError, match="CONTACT"):
        build_sec_service(s, db, FixedClock(datetime(2026, 11, 16, tzinfo=UTC)))
    db.close()
