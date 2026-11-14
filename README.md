# Prooflag

Checks prediction-market resolution rules against the public documents (SEC EDGAR, Federal Register) that settle
them and records every decision with its evidence. No order placement; free public data and local models only.
See `PLAN.md`, `docs/edge-study.md` (E1/E2), `PROGRESS.md`, `DECISIONS.md`.

## Setup
`uv sync`, copy `.env.example` to `.env` and set `PROOFLAG_CONTACT_EMAIL` (sent only to sec.gov, redacted elsewhere),
then `uv run pytest` (no network or model needed), `uv run ruff check .`, `uv run mypy`.

## Running the SEC watcher (live E2 test)
`uv run python scripts/run_sec_watcher.py > data/sec_watcher.log 2>&1` (Ctrl+C to stop; `--once` runs one tick).
It polls `config/watch_ciks.json` (Anthropic, PBC; Strategy Inc) every 30 s in the EDGAR window (06:00-22:00 ET
weekdays), every 15 min otherwise, plus Atom feeds for EFFECT / 424B4 / 424B3 / 424B1 / 8-A12B (about 7 requests per
30 s; SEC cap is 2/s). The first poll of a CIK is a baseline and emits no events.

**Is it alive?** The log starts with `"msg": "sec watcher started"`; a new filing logs a WARNING `"NEW FILING"` with
`accepted_utc`, `detected_utc`, `lag_s`. Health is in table `poll_log` (`sec:submissions:<cik>`, `sec:atom:<form>`):
newest row per source at most 30 s old in the window (15 min outside) with `ok = 1`; repeated `ok = 0` with 403 means a
missing or invalid contact email in `.env`.
