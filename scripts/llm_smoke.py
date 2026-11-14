"""F3: schema-obedience + speed smoke test for local Ollama models (stdlib only).

Usage: python scripts/llm_smoke.py MODEL [MODEL ...]
Writes data/llm_smoke_<model>.json. Thinking disabled, temperature 0, fixed seed.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ENDPOINT = "http://127.0.0.1:11434"
SCHEMA = {
    "type": "object",
    "properties": {
        "trigger": {"type": "string"},
        "evidence_type": {
            "type": "string",
            "enum": ["sec_filing", "federal_register", "court_docket", "press_release", "other"],
        },
        "deadline_text": {"type": ["string", "null"]},
        "deadline_applies_to": {"type": "string", "enum": ["publication", "occurrence", "ambiguous"]},
        "source_span_deadline": {"type": ["string", "null"]},
    },
    "required": [
        "trigger",
        "evidence_type",
        "deadline_text",
        "deadline_applies_to",
        "source_span_deadline",
    ],
    "additionalProperties": False,
}
SYSTEM = (
    "You extract fields from prediction-market resolution rules. Copy spans exactly from the "
    "text. If the rules do not say whether the deadline applies to when the event happens or "
    "when it is publicly reported by the source, answer ambiguous. Output only JSON."
)
RULES = [
    "Resolves Yes if Acme Holdings sells any Bitcoin by May 31, 2026 (11:59 PM ET). The primary "
    "resolution source will be Acme's official SEC filings.",
    "Resolves Yes if an SEC Form 8-K filed on or before Dec 31, 2026 11:59 PM ET reports a CEO "
    "departure at Globex Corp.",
    "The signing date as recorded in the Federal Register determines which week an Executive "
    "Order belongs to. Resolves to the number signed between Nov 8 and Nov 14, 2026.",
    "Resolves Yes if the U.S. Supreme Court grants certiorari in the case before Jan 1, 2027, "
    "per the Supreme Court docket.",
    "This market resolves Yes if Initech announces a new CFO before the end of Q4 2026.",
]


def chat(model: str, rule: str) -> dict:
    body = {
        "model": model,
        "stream": False,
        "think": False,
        "format": SCHEMA,
        "options": {"temperature": 0, "seed": 42, "num_ctx": 4096},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Rules:\n{rule}\n\nReturn the JSON."},
        ],
    }
    req = urllib.request.Request(
        f"{ENDPOINT}/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read().decode())
    d["wall_s"] = time.time() - t0
    return d


def main() -> None:
    for model in sys.argv[1:]:
        rows = []
        for i, rule in enumerate(RULES + [RULES[0]]):  # last = determinism repeat of #0
            d = chat(model, rule)
            text = d["message"]["content"]
            try:
                obj = json.loads(text)
                valid = (
                    set(obj) == set(SCHEMA["properties"])
                    and obj["evidence_type"] in SCHEMA["properties"]["evidence_type"]["enum"]
                    and obj["deadline_applies_to"]
                    in SCHEMA["properties"]["deadline_applies_to"]["enum"]
                )
            except json.JSONDecodeError:
                obj, valid = None, False
            tps = d.get("eval_count", 0) / max(d.get("eval_duration", 1) / 1e9, 1e-9)
            span_ok = bool(obj and (obj["source_span_deadline"] is None or obj["source_span_deadline"] in rule))
            rows.append(
                {
                    "i": i,
                    "valid_schema": valid,
                    "span_verbatim": span_ok,
                    "out": obj,
                    "tok_s": round(tps, 2),
                    "load_s": round(d.get("load_duration", 0) / 1e9, 2),
                    "wall_s": round(d["wall_s"], 1),
                    "eval_count": d.get("eval_count"),
                    "prompt_tokens": d.get("prompt_eval_count"),
                }
            )
            print(model, i, rows[-1]["valid_schema"], rows[-1]["span_verbatim"], rows[-1]["tok_s"], "tok/s", rows[-1]["wall_s"], "s", flush=True)
        deterministic = rows[0]["out"] == rows[-1]["out"]
        summary = {
            "model": model,
            "schema_valid": f"{sum(r['valid_schema'] for r in rows)}/{len(rows)}",
            "spans_verbatim": f"{sum(r['span_verbatim'] for r in rows)}/{len(rows)}",
            "repeat_identical": deterministic,
            "median_tok_s": sorted(r["tok_s"] for r in rows)[len(rows) // 2],
            "rows": rows,
        }
        Path("data").mkdir(exist_ok=True)
        Path(f"data/llm_smoke_{model.replace(':', '_')}.json").write_text(
            json.dumps(summary, indent=1), encoding="utf-8"
        )
        print({k: v for k, v in summary.items() if k != "rows"}, flush=True)


if __name__ == "__main__":
    main()
