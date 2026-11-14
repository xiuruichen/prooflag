from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from prooflag.edge.ipo import REACTION_OFFSETS, reaction
from prooflag.ingest.models import Trade

T = datetime(2026, 10, 26, 13, 0, 11, tzinfo=UTC)


def tr(offset_min: float, price: float, i: int = 0) -> Trade:
    return Trade(T + timedelta(minutes=offset_min), price, 1.0, "yes", f"t{offset_min}-{i}")


def test_reaction_reports_price_moves_relative_to_the_filing_time() -> None:
    series = {
        "A": [tr(-120, 0.30), tr(-5, 0.30), tr(2, 0.50), tr(30, 0.55), tr(70, 0.60), tr(400, 0.62)],
        "B": [tr(-90, 0.10), tr(1, 0.12), tr(20, 0.12), tr(100, 0.13)],
    }
    out = reaction(series, T)
    by = {r.label: r for r in out.rows}
    assert out.n_markets == 2
    # price at T is the last trade at or before T: A 0.30, B 0.10
    assert by["+15 min"].median_change == pytest.approx(((0.50 - 0.30) + (0.12 - 0.10)) / 2)
    assert by["+15 min"].n == 2
    assert by["-1 h"].n == 2  # pre-move uses trades before the filing
    assert by["+24 h"].n == 0  # no trade within the staleness window after +24h: not invented


def test_reaction_skips_markets_with_no_price_at_the_filing_time() -> None:
    out = reaction({"A": [tr(10, 0.5)]}, T)  # first trade is after the filing
    assert out.n_markets == 0 and all(r.n == 0 for r in out.rows)


def test_reaction_offsets_are_the_documented_ones() -> None:
    assert [lbl for lbl, _ in REACTION_OFFSETS] == [
        "-1 h",
        "+1 min",
        "+15 min",
        "+1 h",
        "+6 h",
        "+24 h",
    ]


def test_reaction_also_reports_mean_absolute_change_so_big_moves_are_not_hidden() -> None:
    series = {
        "A": [tr(-5, 0.30), tr(30, 0.60)],  # +0.30
        "B": [tr(-5, 0.50), tr(30, 0.20)],  # -0.30 : the median change is 0, |change| is 0.30
        "C": [tr(-5, 0.10), tr(30, 0.10)],  # 0
    }
    row = {r.label: r for r in reaction(series, T).rows}["+1 h"]
    assert row.median_change == pytest.approx(0.0)
    assert row.mean_abs_change == pytest.approx(0.2)
