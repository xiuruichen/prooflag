from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from prooflag.compiler.compile import compile_rule
from prooflag.llm.provider import FakeProvider

TITLE = "Will X sell any Bitcoin by May 31, 2026?"
RULES = (
    "Resolves Yes if X sells any Bitcoin by 11:59 PM ET on the date specified in the title. "
    "The primary resolution source will be information from X and on-chain data."
)
APPLIES_SPAN = "by 11:59 PM ET on the date specified in the title"


def out(applies: str = "ambiguous") -> dict[str, Any]:
    return {
        "trigger": "X sells any Bitcoin",
        "evidence_type": "other",
        "entity_name": "X",
        "acceptable_forms": [],
        "deadline_text": "11:59 PM ET",
        "deadline_applies_to": applies,
        "revisions_count": None,
        "ambiguity_notes": [],
        "headline_conflict": {"conflict": False, "note": None},
        "source_spans": {
            "trigger": "X sells any Bitcoin",
            "deadline": "11:59 PM ET",
            "deadline_applies_to": APPLIES_SPAN,
            "evidence_type": None,
            "entity": None,
            "revisions_count": None,
            "headline_conflict": None,
            "acceptable_forms": [],
        },
        "confidence": 0.8,
    }


def fake(name: str, payload: dict[str, Any] | str) -> FakeProvider:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return FakeProvider(name, lambda s, u, sc: text)


def test_model_disagreement_forces_ambiguous_and_is_recorded() -> None:
    r = compile_rule(
        TITLE, RULES, None, [fake("qwen", out("occurrence")), fake("llama", out("publication"))]
    )
    assert r.spec.deadline_applies_to == "ambiguous"
    assert r.failed_checks["deadline_applies_to_disagreement"] == {
        "qwen": "occurrence",
        "llama": "publication",
    }


def test_agreement_with_verified_span_is_kept() -> None:
    r = compile_rule(
        TITLE, RULES, None, [fake("qwen", out("occurrence")), fake("llama", out("occurrence"))]
    )
    assert r.spec.deadline_applies_to == "occurrence" and r.valid
    assert r.spec.deadline_utc is not None and r.spec.deadline_tz_original == "ET"


def test_agreement_without_a_verified_span_falls_back_to_ambiguous() -> None:
    bad = out("occurrence")
    bad["source_spans"]["deadline_applies_to"] = "this text is not in the rules"
    r = compile_rule(TITLE, RULES, None, [fake("a", bad), fake("b", bad)])
    assert r.spec.deadline_applies_to == "ambiguous"
    assert "span_unverified:deadline_applies_to" in r.failed_checks["span_failures"]
    assert not r.valid


def test_invalid_json_from_a_model_forces_ambiguous_and_marks_invalid() -> None:
    r = compile_rule(TITLE, RULES, None, [fake("a", "not json"), fake("b", out("occurrence"))])
    assert r.spec.deadline_applies_to == "ambiguous" and not r.valid
    assert "schema_invalid:a" in r.failed_checks["model_errors"]


def test_deterministic_filed_by_phrase_means_publication() -> None:
    rules = "Resolves Yes if an 8-K is filed on or before 11:59 PM ET on January 15, 2027."
    t = out("publication")
    t["source_spans"]["deadline_applies_to"] = "filed on or before 11:59 PM ET"
    t["acceptable_forms"] = ["8-K"]
    r = compile_rule("t", rules, None, [fake("a", t), fake("b", t)])
    assert r.spec.deadline_applies_to == "publication" and r.spec.acceptable_forms == ["8-K"]


def test_a_model_that_contradicts_the_deterministic_phrase_forces_ambiguous() -> None:
    rules = "Resolves Yes if an 8-K is filed on or before 11:59 PM ET on January 15, 2027."
    t = out("occurrence")
    t["source_spans"]["deadline_applies_to"] = "filed on or before 11:59 PM ET"
    r = compile_rule("t", rules, None, [fake("a", t), fake("b", t)])
    assert r.spec.deadline_applies_to == "ambiguous"


def test_naive_timezone_deadline_is_ambiguous() -> None:
    rules = "Resolves Yes if X sells any Bitcoin by 11:59 PM on January 15, 2027."
    t = out("occurrence")
    t["source_spans"]["deadline"] = "11:59 PM"
    t["source_spans"]["deadline_applies_to"] = "by 11:59 PM on January 15, 2027"
    r = compile_rule(TITLE, rules, None, [fake("a", t), fake("b", t)])
    assert r.spec.deadline_utc is None and r.spec.deadline_applies_to == "ambiguous"
    assert r.failed_checks["deadline"] == "naive_timezone"


def test_unverified_headline_conflict_claim_is_discarded() -> None:
    t = out("ambiguous")
    t["headline_conflict"] = {"conflict": True, "note": "title differs"}
    t["source_spans"]["headline_conflict"] = "fabricated span"
    r = compile_rule(TITLE, RULES, None, [fake("a", t), fake("b", t)])
    assert r.spec.headline_conflict is False


def test_verified_headline_conflict_claim_is_kept() -> None:
    t = out("ambiguous")
    t["headline_conflict"] = {"conflict": True, "note": "title says by date, rules say reported"}
    t["source_spans"]["headline_conflict"] = "by 11:59 PM ET"
    r = compile_rule(TITLE, RULES, None, [fake("a", t), fake("b", t)])
    assert r.spec.headline_conflict is True


def test_strategy_fixture_compiles_to_ambiguous_deadline() -> None:
    d = json.loads(
        Path("fixtures/strategy_2026_05/polymarket_market_may31.json").read_text(encoding="utf-8")
    )
    d = d[0] if isinstance(d, list) else d
    t = out("occurrence")
    t["source_spans"]["trigger"] = "MicroStrategy sells any of its Bitcoin"
    t["source_spans"]["deadline_applies_to"] = "by 11:59 PM ET on the date specified in the title"
    r = compile_rule(
        d["question"],
        d["description"],
        None,
        [fake("qwen", t), fake("llama", out("ambiguous"))],
    )
    assert r.spec.deadline_applies_to == "ambiguous"


def test_one_model_cannot_decide_the_deadline_basis() -> None:
    r = compile_rule(TITLE, RULES, None, [fake("qwen", out("publication"))])
    assert r.spec.deadline_applies_to == "ambiguous" and "insufficient_models" in r.failed_checks


def test_two_providers_with_the_same_name_are_not_two_votes() -> None:
    r = compile_rule(
        TITLE, RULES, None, [fake("q", out("occurrence")), fake("q", out("occurrence"))]
    )
    assert r.spec.deadline_applies_to == "ambiguous"


def test_trivial_spans_do_not_justify_a_vote_or_a_conflict_or_a_form() -> None:
    t = out("occurrence")
    t["source_spans"]["deadline_applies_to"] = "X"
    t["headline_conflict"] = {"conflict": True, "note": "made up"}
    t["source_spans"]["headline_conflict"] = "X"
    t["acceptable_forms"] = ["X", "Bitcoin"]
    r = compile_rule(TITLE, RULES, None, [fake("a", t), fake("b", t)])
    assert r.spec.deadline_applies_to == "ambiguous"
    assert r.spec.headline_conflict is False and r.spec.acceptable_forms == []


def test_span_copied_from_the_title_does_not_justify_a_vote() -> None:
    t = out("occurrence")
    t["source_spans"]["deadline_applies_to"] = "Will X sell any Bitcoin"
    r = compile_rule(TITLE, RULES, None, [fake("a", t), fake("b", t)])
    assert r.spec.deadline_applies_to == "ambiguous"


def test_provider_exception_is_recorded_not_raised_and_confidence_is_bounded() -> None:
    def boom(s: str, u: str, sc: dict[str, Any]) -> str:
        raise RuntimeError("down")

    t = out("ambiguous")
    t["confidence"] = -5
    r = compile_rule(TITLE, RULES, None, [FakeProvider("bad", boom), fake("b", t)])
    assert "provider_error:bad" in r.failed_checks["model_errors"] and not r.valid
    assert 0.0 <= r.spec.confidence <= 1.0
