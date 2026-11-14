"""Compile one market's rules with BOTH local models (Qwen3-8B and Llama-3.1-8B) under the model lock.

Usage: uv run python scripts/compile_live.py            (the Strategy fixture)
Prints the spec JSON and failed checks. One model job at a time: exits if data/model.lock is held.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from prooflag.compiler.compile import compile_rule, spec_json
from prooflag.llm.provider import ModelBusyError, ModelLock, OllamaProvider

ROOT = Path(__file__).resolve().parent.parent
MODELS = ("qwen3:8b", "llama3.1:8b")


def main() -> int:
    d = json.loads(
        (ROOT / "fixtures/strategy_2026_05/polymarket_market_may31.json").read_text("utf-8")
    )
    d = d[0] if isinstance(d, list) else d
    try:
        with ModelLock(ROOT / "data" / "model.lock", "compile_live"):
            res = compile_rule(
                d["question"], d["description"], None, [OllamaProvider(m) for m in MODELS]
            )
    except ModelBusyError as e:
        print(e)
        return 1
    print(spec_json(res.spec))
    print(json.dumps(res.failed_checks, indent=1, sort_keys=True))
    print("valid:", res.valid, "models:", res.models)
    return 0


if __name__ == "__main__":
    sys.exit(main())
