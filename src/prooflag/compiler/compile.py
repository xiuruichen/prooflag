"""Rule compiler: deterministic extraction, then local models vote on the deadline basis."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from prooflag.compiler.extract import (
    extract_deadline,
    extract_forms,
    publication_phrase,
    verify_span,
)
from prooflag.llm.provider import LLMProvider, sha256_text

Applies = Literal["publication", "occurrence", "ambiguous"]
Evidence = Literal["sec_filing", "federal_register", "court_docket", "press_release", "other"]

SYSTEM_PROMPT = (
    "You extract fields from prediction-market resolution rules. Copy spans exactly from the "
    "text. If the rules do not say whether the deadline applies to when the event happens or "
    "when it is publicly reported by the source, answer `ambiguous`. Never infer a field you "
    "cannot quote. Output only JSON matching the schema."
)
PROMPT_SHA = sha256_text(SYSTEM_PROMPT)


class _Spans(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trigger: str | None = None
    deadline: str | None = None
    deadline_applies_to: str | None = None
    evidence_type: str | None = None
    entity: str | None = None
    revisions_count: str | None = None
    headline_conflict: str | None = None
    acceptable_forms: list[str] = []


class _Conflict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conflict: bool
    note: str | None = None


class LLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trigger: str
    evidence_type: Evidence
    entity_name: str | None = None
    acceptable_forms: list[str] = []
    deadline_text: str | None = None
    deadline_applies_to: Applies
    revisions_count: bool | None = None
    ambiguity_notes: list[str] = []
    headline_conflict: _Conflict
    source_spans: _Spans
    confidence: float


def _s(t: str, nullable: bool = True) -> dict[str, Any]:
    return {"type": ["string", "null"]} if nullable else {"type": "string"}


LLM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "trigger",
        "evidence_type",
        "deadline_applies_to",
        "headline_conflict",
        "source_spans",
        "confidence",
    ],
    "properties": {
        "trigger": {"type": "string"},
        "evidence_type": {
            "enum": ["sec_filing", "federal_register", "court_docket", "press_release", "other"]
        },
        "entity_name": _s(""),
        "acceptable_forms": {"type": "array", "items": {"type": "string"}},
        "deadline_text": _s(""),
        "deadline_applies_to": {"enum": ["publication", "occurrence", "ambiguous"]},
        "revisions_count": {"type": ["boolean", "null"]},
        "ambiguity_notes": {"type": "array", "items": {"type": "string"}},
        "headline_conflict": {
            "type": "object",
            "additionalProperties": False,
            "required": ["conflict"],
            "properties": {"conflict": {"type": "boolean"}, "note": _s("")},
        },
        "source_spans": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                **{
                    k: _s("")
                    for k in (
                        "trigger",
                        "deadline",
                        "deadline_applies_to",
                        "evidence_type",
                        "entity",
                        "revisions_count",
                        "headline_conflict",
                    )
                },
                "acceptable_forms": {"type": "array", "items": {"type": "string"}},
            },
        },
        "confidence": {"type": "number"},
    },
}


class RuleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules_sha: str
    trigger: str | None
    evidence_type: Evidence
    entity_name: str | None
    acceptable_forms: list[str]
    deadline_text: str | None
    deadline_applies_to: Applies
    deadline_utc: datetime | None
    deadline_tz_original: str | None
    deadline_basis: Literal["acceptance", "filing_date", "unspecified"] = "unspecified"
    revisions_count: bool | None
    ambiguity_notes: list[str]
    headline_conflict: bool
    headline_conflict_note: str | None
    source_spans: dict[str, Any]
    confidence: float


@dataclass
class CompileResult:
    spec: RuleSpec
    valid: bool
    failed_checks: dict[str, Any]
    models: list[tuple[str, str]] = field(default_factory=list)  # (name, model file sha256)
    raw_outputs: dict[str, str] = field(default_factory=dict)
    prompt_sha: str = PROMPT_SHA


def compile_rule(
    title: str,
    rules: str,
    secondary: str | None,
    providers: list[LLMProvider],
    *,
    seed: int = 42,
) -> CompileResult:
    corpus = "\n".join(x for x in (title, rules, secondary) if x)
    rules_sha = sha256_text(corpus)
    user = f"TITLE: {title}\nRULES: {rules}\nSECONDARY: {secondary or ''}"
    dl = extract_deadline(title, "\n".join(x for x in (rules, secondary) if x))
    failed: dict[str, Any] = {}
    span_failures: list[str] = []
    model_errors: list[str] = []
    votes: dict[str, str] = {}
    outputs: list[LLMOutput] = []
    result_models: list[tuple[str, str]] = []
    raw: dict[str, str] = {}

    for p in providers:
        res = p.generate(SYSTEM_PROMPT, user, LLM_SCHEMA, seed=seed)
        result_models.append((res.model_name, res.model_sha256))
        raw[p.model_name] = res.text
        try:
            o = LLMOutput.model_validate_json(res.text)
        except (ValidationError, ValueError):
            model_errors.append(f"schema_invalid:{p.model_name}")
            votes[p.model_name] = "ambiguous"
            continue
        outputs.append(o)
        vote: str = o.deadline_applies_to
        sp = o.source_spans.deadline_applies_to
        if vote != "ambiguous" and not (sp and verify_span(sp, corpus)):
            span_failures.append("span_unverified:deadline_applies_to")
            vote = "ambiguous"
        votes[p.model_name] = vote

    det = publication_phrase(corpus)
    all_votes = set(votes.values()) | ({"publication"} if det else set())
    applies: Applies = "ambiguous"
    if len(all_votes) == 1:
        only = next(iter(all_votes))
        if only == "publication":
            applies = "publication"
        elif only == "occurrence":
            applies = "occurrence"
    elif len(set(votes.values())) > 1 or det:
        failed["deadline_applies_to_disagreement"] = {
            **votes,
            **({"deterministic": "publication"} if det else {}),
        }
    if not providers:
        applies = "ambiguous"
    if dl.status != "ok":
        failed["deadline"] = dl.status
        applies = "ambiguous"

    first = outputs[0] if outputs else None
    spans = first.source_spans.model_dump() if first else {}
    trigger = first.trigger if first else None
    if first and first.source_spans.trigger and not verify_span(first.source_spans.trigger, corpus):
        span_failures.append("span_unverified:trigger")
        trigger = None
    conflict, note = False, None
    if first and first.headline_conflict.conflict:
        hs = first.source_spans.headline_conflict
        if hs and verify_span(hs, corpus):
            conflict, note = True, first.headline_conflict.note
        else:
            span_failures.append("span_unverified:headline_conflict")
    forms = extract_forms(corpus)
    for f in first.acceptable_forms if first else []:
        if f not in forms and verify_span(f, corpus):
            forms.append(f)
    if span_failures:
        failed["span_failures"] = sorted(set(span_failures))
    if model_errors:
        failed["model_errors"] = model_errors

    spec = RuleSpec(
        rules_sha=rules_sha,
        trigger=trigger,
        evidence_type=first.evidence_type if first else "other",
        entity_name=first.entity_name if first else None,
        acceptable_forms=forms,
        deadline_text=dl.span,
        deadline_applies_to=applies,
        deadline_utc=dl.utc,
        deadline_tz_original=dl.tz_original,
        revisions_count=first.revisions_count if first else None,
        ambiguity_notes=first.ambiguity_notes if first else [],
        headline_conflict=conflict,
        headline_conflict_note=note,
        source_spans=spans,
        confidence=min(first.confidence, 1.0) if first and not span_failures else 0.0,
    )
    return CompileResult(spec, not span_failures and not model_errors, failed, result_models, raw)


def spec_json(spec: RuleSpec) -> str:
    return json.dumps(spec.model_dump(mode="json"), sort_keys=True)
