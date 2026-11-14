# Local model smoke test (F3)

Script: `scripts/llm_smoke.py`. Raw output: `data/llm_smoke_*.json` (gitignored). Run date: 2026-11-13,
machine idle, CPU only (12 threads, 14.8 GB RAM). Ollama `/api/chat`, `format=<JSON schema>`,
`think=false`, temperature 0, seed 42, `num_ctx` 4096. 5 rules plus 1 repeat of rule 0 (6 calls per model).
This is a **smoke test, not a benchmark**: n = 5 prompts, no gold labels, so no accuracy claim is made.

| Model | Blob sha256 (GGUF) | Schema-valid | Spans verbatim | Repeat identical | Median tok/s |
|---|---|---|---|---|---|
| qwen3:8b | `a3de86cd1c132c822487ededd47a324c50491393e6565cd14bafa40d0b8e686f` | 6/6 | 6/6 | yes | 6.24 |
| llama3.1:8b | `667b0c1932bc6ffc593ed1d03f895bf2dc8dc6df21db3042284a6f4416b06a29` | 6/6 | 6/6 | yes | 6.65 |

Latency: about 30 to 45 s per call for about 100 prompt tokens and 80 to 120 output tokens (CPU, 8B Q4).

## Findings

1. **Constrained decoding works with thinking disabled** for both models: 12/12 outputs parsed and matched
   the schema; every quoted span was verbatim in the rule text.
2. **Determinism:** identical repeats on an idle machine. An earlier run, with two copies of the script
   hitting Ollama at the same time, produced a differing repeat for qwen3:8b, so bit-exactness is not
   guaranteed under load. The design already replays from cached LLM outputs (`llm_calls`); do not run
   benchmarks concurrently.
3. **Behavior difference (anecdotal, n = 5):** Llama-3.1-8B answered `ambiguous` for the deadline on all
   five rules, including one that said "filed on or before ..." (qwen3 answered `publication`). It may be
   over-abstaining; this must be measured on the gold set before it matters.
4. **Speed:** about 6 tok/s means roughly 30+ s per compile or evaluation call. A 65-item gold run is
   about 40 minutes per model per pass; plan the benchmark overnight and keep prompts short (the
   lexical prefilter and chunking in the plan are required, not optional).
5. Qwen3-4B was not pulled: 8B speed is acceptable for this workload (fallback rule unchanged).
