from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from prooflag.edge.eo import (
    ET,
    EoDoc,
    Rule,
    deciding_eo,
    dedupe,
    implied_result,
    in_window,
    parse_rule,
)

D = date


def eo(num, sign, pub, pi=None, doc=None):  # type: ignore[no-untyped-def]
    return EoDoc(num, doc or f"d{num}", sign, pub, pi)


def utc(y, mo, d, h=0, mi=0):  # type: ignore[no-untyped-def]
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


# Rule texts below are the real forms found on 123 Kalshi KXEOWEEK markets.
@pytest.mark.parametrize(
    ("text", "kind", "n", "start", "end", "needed"),
    [
        (
            "If the President signs above 0 executive orders during Sep 20, 2026 to Sep 26, 2026, "
            "then the market resolves to Yes.",
            "above",
            0,
            D(2026, 9, 20),
            D(2026, 9, 26),
            1,
        ),
        (
            "If the President signs above 3 Executive Orders during Aug 30, 2026 to Sep 5, 2026, "
            "then the market resolves to Yes.",
            "above",
            3,
            D(2026, 8, 30),
            D(2026, 9, 5),
            4,
        ),
        (
            "If the President signs any Executive Orders during Nov 30, 2025 to Dec 6, 2025, then "
            "the market resolves to Yes.",
            "any",
            0,
            D(2025, 11, 30),
            D(2025, 12, 6),
            1,
        ),
        (
            "If the President signs any Executive Orders from Jan 4, 2026 to Jan 10, 2026, then the "
            "market resolves to Yes.",
            "any",
            0,
            D(2026, 1, 4),
            D(2026, 1, 10),
            1,
        ),
        (
            "If the President signs at least 2 executive orders during Oct 4, 2026 to Oct 10, 2026, "
            "then the market resolves to Yes.",
            "at_least",
            2,
            D(2026, 10, 4),
            D(2026, 10, 10),
            2,
        ),
        (
            "If the President signs exactly 2 Executive Orders during Oct 4, 2026 to Oct 10, 2026, "
            "then the market resolves to Yes.",
            "exactly",
            2,
            D(2026, 10, 4),
            D(2026, 10, 10),
            None,
        ),
        (
            "If the President signs above 1 Executive Orders between Oct 4, 2026 to Oct 10, 2026, "
            "then the market resolves to Yes.",
            "above",
            1,
            D(2026, 10, 4),
            D(2026, 10, 10),
            2,
        ),
    ],
)
def test_parse_rule_real_forms(text, kind, n, start, end, needed) -> None:  # type: ignore[no-untyped-def]
    r = parse_rule(text)
    assert r == Rule(kind, n, start, end)
    assert r is not None and r.needed == needed


def test_parse_rule_rejects_unknown_text() -> None:
    assert parse_rule("Resolves Yes if it rains.") is None
    assert parse_rule("") is None


def test_dedupe_by_eo_number_keeps_earliest_posting_and_handles_missing_numbers() -> None:
    first = eo(14388, D(2026, 2, 20), D(2026, 2, 25), utc(2026, 2, 24, 16), doc="2026-001")
    reissue = eo(14388, D(2026, 2, 20), D(2026, 4, 9), utc(2026, 4, 8, 12), doc="R1-2026-03829")
    other = eo(14389, D(2026, 2, 21), D(2026, 2, 26), utc(2026, 2, 25, 16))
    nonum = eo(None, D(2026, 2, 22), D(2026, 2, 27), None, doc="x1")
    out = dedupe([reissue, first, other, nonum])
    assert [e.doc_number for e in out] == ["2026-001", "d14389", "x1"]


def test_window_is_by_signing_date_inclusive() -> None:
    es = [
        eo(1, D(2026, 9, 19), D(2026, 9, 24)),
        eo(2, D(2026, 9, 20), D(2026, 9, 24)),
        eo(3, D(2026, 9, 26), D(2026, 9, 30)),
        eo(4, D(2026, 9, 27), D(2026, 9, 30)),
    ]
    assert [e.number for e in in_window(es, D(2026, 9, 20), D(2026, 9, 26))] == [2, 3]


def test_implied_result() -> None:
    r_above = Rule("above", 2, D(2026, 1, 1), D(2026, 1, 7))
    assert [implied_result(r_above, c) for c in (0, 2, 3)] == ["no", "no", "yes"]
    assert implied_result(Rule("any", 0, D(2026, 1, 1), D(2026, 1, 7)), 1) == "yes"
    assert implied_result(Rule("at_least", 2, D(2026, 1, 1), D(2026, 1, 7)), 1) == "no"
    assert implied_result(Rule("exactly", 2, D(2026, 1, 1), D(2026, 1, 7)), 2) == "yes"
    assert implied_result(Rule("exactly", 2, D(2026, 1, 1), D(2026, 1, 7)), 3) == "no"


def test_t_pub_is_0600_et_on_the_publication_date_and_dst_aware() -> None:
    e = eo(1, D(2026, 7, 1), D(2026, 7, 7))  # EDT: 06:00 ET = 10:00Z
    assert e.t_pub == datetime(2026, 7, 7, 6, 0, tzinfo=ET)
    assert e.t_pub.astimezone(UTC) == utc(2026, 7, 7, 10)
    w = eo(2, D(2026, 12, 1), D(2026, 12, 7))  # EST: 06:00 ET = 11:00Z
    assert w.t_pub.astimezone(UTC) == utc(2026, 12, 7, 11)


def test_deciding_eo_is_the_nth_smallest_posting_time_not_the_nth_signed() -> None:
    # Signed order 1,2,3 but EO 2 is posted LAST: for "above 1" (needs 2 EOs) the second EO to
    # appear publicly is EO 3, not EO 2 (the second signed).
    es = [
        eo(1, D(2026, 9, 21), D(2026, 9, 24), utc(2026, 9, 23, 15)),
        eo(2, D(2026, 9, 22), D(2026, 9, 29), utc(2026, 9, 28, 15)),
        eo(3, D(2026, 9, 23), D(2026, 9, 25), utc(2026, 9, 24, 15)),
    ]
    r = Rule("above", 1, D(2026, 9, 20), D(2026, 9, 26))
    pi = deciding_eo(r, es, "pi")
    assert pi is not None and pi.number == 3
    pub = deciding_eo(r, es, "pub")
    assert pub is not None and pub.number == 3
    assert (
        deciding_eo(Rule("above", 3, D(2026, 9, 20), D(2026, 9, 26)), es, "pi") is None
    )  # needs 4


def test_deciding_eo_pi_vs_pub_bases_can_differ_and_missing_pi_is_excluded() -> None:
    es = [
        eo(1, D(2026, 9, 21), D(2026, 9, 25), utc(2026, 9, 24, 15)),
        eo(2, D(2026, 9, 21), D(2026, 9, 24), None),  # PI time unknown
    ]
    r = Rule("any", 0, D(2026, 9, 20), D(2026, 9, 26))
    assert deciding_eo(r, es, "pi").number == 1  # type: ignore[union-attr]
    assert deciding_eo(r, es, "pub").number == 2  # type: ignore[union-attr]  # published earlier


def test_posting_time_ordering_ties_are_stable() -> None:
    t = utc(2026, 9, 24, 15)
    es = [eo(2, D(2026, 9, 21), D(2026, 9, 25), t), eo(1, D(2026, 9, 21), D(2026, 9, 25), t)]
    r = Rule("above", 0, D(2026, 9, 20), D(2026, 9, 26))
    assert deciding_eo(r, es, "pi").number == 1  # type: ignore[union-attr]  # tie broken by number


def test_timedelta_import_used() -> None:
    assert timedelta(minutes=1).total_seconds() == 60
