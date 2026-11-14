from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fakes import T0, FakeSource, mk


def test_catalog_second_pass_reports_rule_edits(make_env) -> None:  # type: ignore[no-untyped-def]
    src = FakeSource("kalshi", [mk("A")])
    env = make_env(src)
    env.svc.catalog_pass("kalshi")
    src.catalog = [mk("A", rules_primary="Resolved per the Federal Register, by publication.")]
    st = env.svc.catalog_pass("kalshi")
    assert (st.new, st.rules_changed) == (0, 1)
    assert env.one("select count(*) from market_rule_changes")[0] == 1


def test_one_bad_market_does_not_abort_the_pass(make_env) -> None:  # type: ignore[no-untyped-def]
    bad = mk("BAD")
    bad.close_time = "not-a-datetime"  # type: ignore[assignment]  # breaks serialization
    env = make_env(FakeSource("kalshi", [mk("A"), bad, mk("B")]))
    st = env.svc.catalog_pass("kalshi")
    assert st.errors == 1 and st.new == 2
    assert env.one("select count(*) from markets")[0] == 2


def test_snapshot_pass_only_watched_live_markets_with_bid_ask_last(make_env) -> None:  # type: ignore[no-untyped-def]
    src = FakeSource("kalshi", [mk("A"), mk("B", vol24_usd_est=1.0)])
    env = make_env(src)
    env.allow("kalshi", "A")
    env.svc.catalog_pass("kalshi")
    st = env.svc.snapshot_pass()
    assert src.lookup_calls == [["A"]]  # B is not watched
    assert st.snapshots == 1 and st.missing == 0
    row = env.one("select * from price_snapshots")
    assert (row["market_id"], row["ts_utc"], row["source"]) == ("A", T0.isoformat(), "snapshot")
    assert (row["yes_bid"], row["yes_ask"], row["last_price"]) == (0.1, 0.2, 0.15)


def test_watched_market_stays_in_snapshots_after_volume_dips(make_env) -> None:  # type: ignore[no-untyped-def]
    src = FakeSource("kalshi", [mk("A")])
    env = make_env(src)
    env.allow_catalog()
    env.svc.catalog_pass("kalshi")
    src.catalog = [mk("A", vol24_usd_est=0.0)]
    env.svc.catalog_pass("kalshi")
    env.svc.snapshot_pass()
    assert src.lookup_calls[-1] == ["A"]
    assert env.one("select watched, meaningful from markets")[:] == (1, 0)


def test_past_end_polymarket_market_is_still_snapshotted_until_settled(make_env) -> None:  # type: ignore[no-untyped-def]
    pm = mk(
        "0xP",
        venue="polymarket",
        series_ticker=None,
        event_title="Strategy",
        status="open",
        vol24_usd_est=9000.0,
        token_ids={"yes": "TY", "no": "TN"},
    )
    src = FakeSource("polymarket", [pm])
    env = make_env(src)
    env.allow_catalog()
    env.svc.catalog_pass("polymarket")
    src.lookups["0xP"] = mk(
        "0xP", venue="polymarket", series_ticker=None, status="past_end", vol24_usd_est=0.0
    )
    env.clock.advance(timedelta(minutes=5))
    st = env.svc.snapshot_pass()
    assert st.snapshots == 1 and env.one("select status from markets")[0] == "past_end"
    # Resolution arrives: final snapshot is taken, then the market leaves the target set.
    src.lookups["0xP"] = mk(
        "0xP",
        venue="polymarket",
        series_ticker=None,
        status="settled",
        result="no",
        last_price=0.0,
        yes_bid=0.0,
        yes_ask=0.0,
    )
    env.clock.advance(timedelta(minutes=5))
    st = env.svc.snapshot_pass()
    assert st.snapshots == 1 and st.settled == 1
    row = env.one("select status, result, settled_at from markets")
    assert (row["status"], row["result"]) == ("settled", "no") and row["settled_at"]
    env.clock.advance(timedelta(minutes=5))
    assert env.svc.snapshot_pass().snapshots == 0
    assert env.one("select count(*) from price_snapshots")[0] == 2


def test_missing_from_lookup_is_reported_and_left_unchanged(make_env) -> None:  # type: ignore[no-untyped-def]
    src = FakeSource("kalshi", [mk("A"), mk("B")])
    env = make_env(src)
    env.allow_catalog()
    env.svc.catalog_pass("kalshi")
    del src.lookups["B"]
    st = env.svc.snapshot_pass()
    assert st.snapshots == 1 and st.missing == 1
    assert env.one("select status from markets where market_id='B'")[0] == "open"


def test_venue_outage_is_logged_and_other_venues_continue(make_env) -> None:  # type: ignore[no-untyped-def]
    k = FakeSource("kalshi", [mk("A")])
    p = FakeSource(
        "polymarket", [mk("0xP", venue="polymarket", series_ticker=None, token_ids={"yes": "TY"})]
    )
    env = make_env(k, p)
    env.allow_catalog()
    env.svc.catalog_pass("kalshi")
    env.svc.catalog_pass("polymarket")
    k.fail_lookup = True
    st = env.svc.snapshot_pass()
    assert st.snapshots == 1 and st.failed_venues == ["kalshi"]
    err = env.one("select ok, err from poll_log where source='snapshot:kalshi' order by id desc")
    assert err["ok"] == 0 and "venue down" in err["err"]


def test_rule_edit_found_during_snapshot_refresh(make_env) -> None:  # type: ignore[no-untyped-def]
    src = FakeSource("kalshi", [mk("A")])
    env = make_env(src)
    env.allow_catalog()
    env.svc.catalog_pass("kalshi")
    src.lookups["A"] = mk("A", rules_primary="Silently edited.", series_ticker=None)
    st = env.svc.snapshot_pass()
    assert st.rules_changed == 1
    assert env.one("select count(*) from market_rule_changes")[0] == 1


def test_ingest_primary_series_covers_open_and_settled_weeks(make_env) -> None:  # type: ignore[no-untyped-def]
    weeks = [
        mk("W1", series_ticker="KXEOWEEK", event_id="KXEOWEEK-26NOV14", status="open"),
        mk(
            "W0",
            series_ticker="KXEOWEEK",
            event_id="KXEOWEEK-26NOV07",
            status="settled",
            result="yes",
            vol24_usd_est=0.0,
        ),
    ]
    src = FakeSource("kalshi", weeks)
    env = make_env(src)
    env.allow("kalshi", "KXEOWEEK", scope="series")
    st = env.svc.ingest_series("kalshi", "KXEOWEEK")
    assert st.new == 2
    assert {s for s, _ in src.series_calls} == {"open", "closed", "settled"}
    rows = {r["market_id"]: r for r in env.db.conn.execute("select * from markets")}
    assert rows["W0"]["status"] == "settled" and rows["W0"]["result"] == "yes"
    assert (
        rows["W0"]["cluster_id"] == "weekly_eo:2026-11-07"
        and rows["W1"]["cluster_id"] == "weekly_eo:2026-11-14"
    )
    assert rows["W0"]["watched"] == 1  # primary eval source even once settled (for backfill)
    tags = {r[0] for r in env.db.conn.execute("select tag from market_tags where market_id='W0'")}
    assert {"weekly_eo", "primary_eval"} <= tags
    env.svc.snapshot_pass()
    assert src.lookup_calls[-1] == ["W1"]  # settled week is not snapshotted


def test_backfill_runs_once_per_watched_market_and_uses_yes_token(make_env) -> None:  # type: ignore[no-untyped-def]
    k = FakeSource("kalshi", [mk("A")])
    p = FakeSource(
        "polymarket",
        [mk("0xP", venue="polymarket", series_ticker=None, token_ids={"yes": "TY", "no": "TN"})],
    )
    env = make_env(k, p)
    env.allow_catalog()
    env.svc.catalog_pass("kalshi")
    env.svc.catalog_pass("polymarket")
    st = env.svc.backfill_pass()
    assert st.markets == 2 and st.points == 6
    assert k.history_calls[0]["series"] == "S" and k.history_calls[0]["token"] is None
    assert p.history_calls[0]["token"] == "TY"
    assert k.history_calls[0]["start"] == T0 - timedelta(days=3)  # market open time
    assert k.history_calls[0]["end"] == T0
    rows = env.db.conn.execute(
        "select count(*) from price_snapshots where source='history'"
    ).fetchone()[0]
    assert rows == 6
    assert env.svc.backfill_pass().markets == 0  # history_through set: not repeated
    assert env.one("select history_through from markets where market_id='A'")[0] == T0.isoformat()


def test_backfill_respects_max_markets_per_pass(make_env) -> None:  # type: ignore[no-untyped-def]
    src = FakeSource("kalshi", [mk(f"M{i}", vol24_usd_est=5000.0) for i in range(5)])
    env = make_env(src)
    env.allow_catalog()
    env.svc.catalog_pass("kalshi")
    assert env.svc.backfill_pass(max_markets=2).markets == 2
    assert env.svc.backfill_pass(max_markets=10).markets == 3


def test_backfill_of_settled_market_stops_at_close_time(make_env) -> None:  # type: ignore[no-untyped-def]
    closed = T0 - timedelta(days=1)
    src = FakeSource(
        "kalshi",
        [
            mk(
                "W0",
                series_ticker="KXEOWEEK",
                event_id="KXEOWEEK-26NOV07",
                status="settled",
                result="no",
                close_time=closed,
            )
        ],
    )
    env = make_env(src)
    env.allow("kalshi", "KXEOWEEK", scope="series")
    env.svc.ingest_series("kalshi", "KXEOWEEK")
    env.svc.backfill_pass()
    assert src.history_calls[0]["end"] == closed


def test_tick_runs_snapshots_by_cadence_and_catalog_by_interval(make_env) -> None:  # type: ignore[no-untyped-def]
    src = FakeSource("kalshi", [mk("A")])
    env = make_env(src)
    env.allow_catalog()
    r1 = env.svc.run_due()
    assert r1.catalog_ran and r1.snapshot_ran
    assert not env.svc.run_due().snapshot_ran  # nothing due immediately after
    env.clock.advance(timedelta(minutes=4, seconds=59))
    assert not env.svc.run_due().snapshot_ran
    env.clock.advance(timedelta(seconds=1))  # 5 min: fast cadence inside the EDGAR window
    r = env.svc.run_due()
    assert r.snapshot_ran and not r.catalog_ran
    # Off-window (Saturday 10:00 ET): 30 min cadence.
    env.clock._t = datetime(2026, 11, 14, 15, 0, tzinfo=UTC)
    assert env.svc.run_due().snapshot_ran
    env.clock.advance(timedelta(minutes=29))
    assert not env.svc.run_due().snapshot_ran
    env.clock.advance(timedelta(minutes=1))
    assert env.svc.run_due().snapshot_ran
    env.clock.advance(timedelta(minutes=60))
    assert env.svc.run_due().catalog_ran  # catalog interval (60 min) elapsed


def test_schedule_registers_the_tick_job() -> None:
    from apscheduler.schedulers.background import BackgroundScheduler

    from prooflag.ingest.jobs import schedule

    sched = BackgroundScheduler()
    schedule(sched, lambda: None, tick_seconds=60)  # type: ignore[arg-type]
    jobs = sched.get_jobs()
    assert [j.id for j in jobs] == ["ingest_tick"]
    assert jobs[0].max_instances == 1 and jobs[0].coalesce
