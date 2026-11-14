# Scripts

| Script | Purpose | Network |
|---|---|---|
| `run_sec_watcher.py [--once]` | Poll SEC EDGAR for watched CIKs and log new filings with detection lag | SEC |
| `e2_run.py` | E2 runner: finds the Anthropic EFFECT / 424B events, fetches prices, writes `studies/e2/results.*` | SEC, venues |
| `edge_study.py` | Regenerate `docs/edge-study.md` from `studies/e1/inputs/` | none |
| `edge_fetch.py` | Re-fetch the E1 inputs (writes `studies/e1/inputs/`) | venues, Federal Register |
| `compile_live.py` | Compile the Strategy rule with both local models (needs Ollama; takes the model lock) | local |
| `run_ingest_once.py` | One ingest pass for Kalshi and Polymarket into the local DB | venues |
| `slice_count.py`, `classify_slice.py` | Count and classify open markets that settle on public documents | venues |
| `build_allowlist_seed.py`, `review_dump.py`, `link_entities.py` | Build and review the watch allow-list and entity links | SEC / local |
| `timing_edgar.py`, `timing_fedreg.py` | Produced `docs/edgar-timing.md` and `docs/fedreg-timing.md` | SEC, Federal Register |
| `record_ingest_fixtures.py` | Record venue responses as test fixtures | venues |
| `llm_smoke.py` | Schema-obedience smoke test for the local models (`docs/model-smoke.md`) | local |
| `check_no_trading.py` | CI check: fails if trading or order endpoints appear in `src/` | none |
