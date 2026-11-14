<div align="center">

# Prooflag

**Do prediction-market prices lag the public documents that settle them?**
A research tool that collects prediction-market resolution rules and the SEC EDGAR and Federal Register filings that settle them, so the two can be compared, with provenance on every result and deterministic replay.

[![ci](https://github.com/xiuruichen/prooflag/actions/workflows/ci.yml/badge.svg)](https://github.com/xiuruichen/prooflag/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.11%2B-3776ab)
![license](https://img.shields.io/badge/license-MIT-green)
![status](https://img.shields.io/badge/status-research%20archive-lightgrey)

<img src="docs/assets/workflow.svg" alt="Animated workflow: market data and public documents flow into an append-only SQLite store and an evidence locker; a two-model rule compiler and the pre-registered studies read from them" width="100%">

</div>

> **Status: research archive.** Not maintained as a trading tool. There is no order-placement code in this repository, and CI greps `src/` for order endpoints. Nothing here is financial advice.

## What we found

| Study | Result | Detail |
|---|---|---|
| **E1: Federal Register executive orders** (weekly Kalshi markets, 24 independent weeks) | **NO SPEED EDGE.** Prices move at signing, about 3 days before public inspection. In 22 of 24 weeks the price was already at 0.90 or above. | [`docs/edge-study.md`](docs/edge-study.md) |
| **Strategy 8-K** (Polymarket, "sells any Bitcoin by May 31, 2026?") | The price moved **before** the filing was accepted. Buying after it lost money, and the deadline wording (does it apply to the sale or to its publication?) decided the resolution. | [`studies/WRITEUP.md`](studies/WRITEUP.md) §3 |
| **Anthropic S-1, S-1/A, FWP** | No market move on any of the leading filings (price change within ±0.007 at every horizon). | [`studies/WRITEUP.md`](studies/WRITEUP.md) §4 |
| **E2: Anthropic EFFECT and 424B** | Pre-registered before the events. **Verdict pending.** | [`studies/e2/`](studies/e2/) |

Full write-up: [`studies/WRITEUP.md`](studies/WRITEUP.md). The honest conclusion so far is that being first to a public document is not an edge on these paths. The more useful product is checking what a rule actually says.

## What it does

- **Ingests** rules, prices and trades from Kalshi and Polymarket into an append-only SQLite store, keeping every version of a rule.
- **Watches** SEC EDGAR for new filings and records EDGAR's acceptance time next to the time Prooflag first saw it, so detection lag is measured and not assumed.
- **Compiles rules** into a structured spec. Two local models (Qwen3-8B and Llama-3.1-8B) vote on whether a deadline applies to an event or to its publication. If they disagree, or any quoted span is not verbatim in the rule, or the timezone is unclear, the answer is `ambiguous`. The Strategy rule compiled to `ambiguous` in a live run with both models (a unit test checks the logic with fake models).
- **Replays** studies from the committed inputs with no network, and regenerates the report with the verdict computed by code from rules fixed in advance.

**Not built:** the evaluator (checking a filing against a compiled spec), the signal layer and the web case file. They appear dashed in the diagram above and are planned, not built.

## Quickstart

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/xiuruichen/prooflag.git && cd prooflag
uv sync
cp .env.example .env            # then edit it: put a real contact address in PROOFLAG_CONTACT_EMAIL
uv run pytest                   # no network or model needed
```

The SEC requires a declared contact in the `User-Agent`. The address is read from `.env`, sent only in SEC-bound User-Agents, and redacted from logs and stored provenance. The watcher, E2 runner and fetch script stop with a clear message if it is missing.

```bash
uv run python scripts/run_sec_watcher.py --once   # one poll, prints detection lag, exits
uv run python scripts/run_sec_watcher.py          # keep polling; Ctrl+C to stop
uv run python scripts/edge_study.py               # replay E1 offline and regenerate docs/edge-study.md
uv run python scripts/run_ingest_once.py          # first: fill the local DB (the E2 runner reads it)
uv run python scripts/e2_run.py                   # E2 runner (writes studies/e2/results.md; PENDING until the events exist)
```

How to check the watcher is alive: [`docs/sec-watcher.md`](docs/sec-watcher.md). Ollama with `qwen3:8b` and `llama3.1:8b` is needed **only** for the rule compiler (`scripts/compile_live.py`). Everything else runs without it.

## Architecture

- **Evidence locker.** Every fetched document is stored by SHA-256 with its source URL and fetch time. The same bytes are stored once.
- **Append-only SQLite.** Triggers reject `UPDATE` and `DELETE` on history tables (rule versions, prices, artifacts, specs, model calls). Runs in WAL mode.
- **Provenance and replay.** Every derived row points to a provenance record: input hashes, model file hash, prompt hash and code version. Model outputs are cached by input, model and prompt, so replay never re-infers.
- **Rule compiler.** Deterministic extraction first (dates and timezones, form types), then the two models. Each model must quote a verbatim span for its answer. Daylight-saving gaps, several dates in one rule and wrong-season `EST`/`EDT` all resolve to `ambiguous`, never to a guess.
- **Entity linker.** Returns a CIK only on exactly one match. Anything else goes to a review queue.

More: [`docs/ingest.md`](docs/ingest.md), [`docs/sec-watcher.md`](docs/sec-watcher.md), [`docs/edgar-timing.md`](docs/edgar-timing.md), [`docs/fedreg-timing.md`](docs/fedreg-timing.md).

## Methodology

- **Pre-registration.** Verdict rules are written before looking at results and the verdict is computed by code. E2's rules are in [`studies/e2/preregistration.md`](studies/e2/preregistration.md), with a dated pre-event amendment.
- **Small samples are reported as such.** Wilson intervals, and the unit of analysis is the week or issuer cluster, not the market.
- **Trade-level data.** Second-resolution trades from Kalshi, so timing claims do not rest on candles.
- **Fee model.** Kalshi's standard schedule using each series' fee type, Polymarket's `feeSchedule`. Fee-free numbers are shown too.

## Disclaimer

This is research code, not financial advice, and it contains no trading functionality. Use of venue data is subject to each venue's terms (see [`fixtures/README.md`](fixtures/README.md)). **SEC fair access:** requests carry a declared User-Agent and are limited to 2 per second. Do not raise it. SEC allows up to 10, and this project deliberately stays well below.

## Project layout

```
src/prooflag/   ingest, linker, watchers, compiler, llm, store, edge (study code)
scripts/        runnable entry points (see scripts/README.md)
studies/        E1 inputs, E2 pre-registration and runner output, WRITEUP.md
docs/           design notes and timing studies; docs/dev-history/ holds the original plan and logs
```

License: [MIT](LICENSE). Contributing: [CONTRIBUTING.md](CONTRIBUTING.md). Security: [SECURITY.md](SECURITY.md). Cite: [CITATION.cff](CITATION.cff).
