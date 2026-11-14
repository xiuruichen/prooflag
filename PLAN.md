# Prooflag — Implementation Plan

> Status: APPROVED with changes (see "Approval changes" below). Project root: `C:\dev\prooflag` (own git repo). DB and evidence locker: `C:\dev\prooflag\data\` (gitignored). No OneDrive, no nested repo.
>
> **Approval changes (applied throughout):** (1) Run F2 slice count FIRST as a standalone script, before F1 scaffolding; stop and report if NO-GO. (2) Benchmark Qwen3-8B + one non-Qwen ~7–9B control only; Qwen3-4B is a fallback only if 8B is too slow. (3) Gold rules set may sample closed/resolved markets to reach the ambiguous-deadline quota. (4) Price-snapshot cadence: tagged markets every 5 min during the EDGAR window, 30 min otherwise. (5) Timeline may be ~1.5 weekends; priority order if time runs short: slice count → store/ingest/SEC watcher → compiler → labeling → evaluator + gate → replay → web case files → notifications/ledger/weekly report.
> **Context:** Prooflag is a personal, zero-cost research instrument that compares prediction-market resolution rules against the public documents (first SEC EDGAR) that settle them, and raises explainable, evidence-backed signals (evidence_gap, deadline_risk, ambiguity). It exists because rules like "by May 31" often hide whether the *event* or its *publication* must meet the deadline. Success = every alert reproducible from stored evidence, with measured accuracy; no trading.
> **Global constraints:** Python 3.11+ (3.12.4 present); httpx, SQLite WAL, Pydantic v2, APScheduler, FastAPI, Jinja2, HTMX; SEC ≤ 2 req/s, declared User-Agent; temp 0 + fixed seed + pinned model hash; no network in tests; no paid services; no order placement; structured JSON logging (stdlib `logging` + JSON formatter) everywhere.
>
> **Approval changes, round 2 (post slice review; applied throughout):**
> 1. **MVP sources = EDGAR + Federal Register.** `watchers/fedreg` moves from interface-only to MVP, using the free FederalRegister.gov API incl. the Public Inspection desk. Courts/CourtListener is the **first post-MVP milestone** (largest family: 20 events), not open-ended phase 2.
> 2. **Federal Register timing is verified in F4** (alongside EDGAR) and written to `docs/fedreg-timing.md`: does a public-inspection posting precede official publication, by how much, which API fields, how reliably.
> 3. **Weekly Executive Order series is the main eval/feedback source** (settles weekly; resolves on the Federal Register signing/publication record).
> 4. **"Meaningful" tightened:** 24h volume ≥ $1,000 (or another real-activity signal, e.g. ≥ 5 trades/24h); Kalshi OI alone with zero volume does not count. Full classified list stays in `data/slice_classified.json`.
> 5. **Anthropic/OpenAI IPO markets are ONE correlated cluster** in evals and the ledger (`cluster_id`); never counted as independent wins.
>
> **Slice result (F2, hand-reviewed):** strict DOC_SETTLED = 33 events / 66 markets (SEC 8/21, Federal Register 5/23, court/agency 20/22); **with the tightened filter (estimated 24h DOLLAR volume ≥ $1,000; Kalshi volume is in contracts, so it is converted as contracts × last price): 15 strict markets in 4 independent clusters** (corrected from 19/4, which compared Kalshi contracts to dollars): Anthropic/OpenAI IPO family 11 markets, Trump election-interference emergency 1, Ilhan Omar denaturalization 2, current-week EO 1. Live volume is thin and concentrated; the weekly EO series (new cluster every week) is the main renewable supply of independent cases, which is why it is the eval priority. Any-of = 35 events / 119 markets (not counted). Scripts: `scripts/slice_count.py`, `scripts/classify_slice.py`.
>
> Environment verified: the home dir `C:\Users\chenf` is itself a git repo, so the project lives outside it at `C:\dev\prooflag` with its own repo (Q9/Q10 resolved). Python 3.12.4, Windows 11, 12 threads, 14.8 GB RAM, AMD iGPU (no usable CUDA), Ollama installed, no `llama-server`. Installed Ollama models are vision-language only (`qwen3-vl:2b-instruct`, `playbook-vl`); a text model must be pulled.

## 0. Clarifying questions (answer or accept the default)

(Numbering note: Q10–Q13 were added after recon and sit next to the question they relate to.)

| # | Question | Default I will assume |
|---|---|---|
| Q1 | **RESOLVED:** Polymarket market "MicroStrategy sells any Bitcoin by May 31, 2026?", reported June–July 2026 with a UMA dispute and a lawsuit (per user, unverified until archived). Search closed Gamma markets for "MicroStrategy"/"Strategy" + "Bitcoin". | F5: bounded search of closed/archived Gamma markets plus Strategy's EDGAR submissions JSON for 2026-05-25..06-05. If still not found, the fixture is a **clearly labeled synthetic fixture**; no rule text is invented for the real market. |
| Q2 | **Polymarket US API:** I could not verify a public market-data API. Do you have docs or a link? | Enum value `polymarket_us` is kept, but **no ingester is planned**. International Polymarket (Gamma/CLOB) is read-only data. |
| Q3 | **SEC contact email for User-Agent** | `.env` value `PROOFLAG_CONTACT_EMAIL`; placeholder committed in `.env.example`, never your real address. |
| Q4 | **Evaluator precision gate.** The Wilson 95% lower bound for 8/8 correct is only ~0.68; reaching 0.80 needs 16/16 correct *predicted-yes*. With 25 pairs and abstention preferred, the gate probably cannot open this weekend. Options: (a) grow the pairs set to ~100 so the ~40% test split holds ≥16 predicted-yes (≈60 pairs is not enough), (b) gate on a lower bound of 0.70, (c) keep evidence_gap disabled until live review labels accumulate. | **(c)**, with (a) as a later top-up from review-queue labels: evidence_gap ships disabled; gate rule = observed precision ≥ 0.95 AND Wilson lower bound ≥ `gate_lb` (default 0.80) AND ≥ `gate_min_yes` (default 16) *predicted-yes* items. Both knobs in config. |
| Q10 | **RESOLVED:** home dir is a git repo; project uses its own repo at `C:\dev\prooflag` (not nested). | Done. |
| Q11 | **deadline_risk scope.** The Strategy case (event before deadline, filing after) cannot be detected live from EDGAR alone before the filing appears. | MVP: (i) *structural* rule — market is publication- or ambiguous-deadline AND the form's legal filing-lag window (e.g. 8-K: 4 business days; verify before use) overlaps the deadline, so late publication is structurally possible; (ii) *post-hoc/replay* detection of acceptance > deadline with event_date ≤ deadline. Pre-filing occurrence feeds (on-chain, news) are phase 2. |
| Q12 | **Outcome ledger / weekly summary** is required in the brief but low priority for a weekend. | Build the ledger (outcomes table + +1h/+6h/settle tracker job + `prooflag weekly` report command) in U7; if time runs out, ship the table and tracker, defer the report. Descope is recorded, not silent. |
| Q13 | **"Meaningful" market (go/no-go).** | ≥ 20 live markets matching a document source AND each with 24h volume ≥ $1,000 or open interest ≥ $2,000. Numbers configurable in the script. |
| Q5 | **"Publication" definition.** EDGAR has two times: acceptance datetime and the official filing date (filings accepted after 5:30 pm ET count as the next business day for most forms). | Store both. The deadline check records which one it used. A rule that does not say which one is an **ambiguity** trigger. |
| Q6 | **Price thresholds** for evidence_gap (e.g. YES < 0.90 when evidence says yes) | `evidence_gap_max_price = 0.90`, configurable per run. |
| Q7 | **Model tier:** this machine is the 16 GB CPU-only tier. OK to benchmark Qwen3-4B vs 8B vs a non-Qwen candidate, choosing by gold-set accuracy? | Yes. |
| Q8 | **RESOLVED (round 3): no manual labeling.** Gold labels come from an AI consensus panel (see §6 "Labeling panel" and S6). | Done. |
| Q9 | **RESOLVED:** repo at `C:\dev\prooflag`; DB and locker under `C:\dev\prooflag\data\` (gitignored). | Done. |
| Q14 | **RESOLVED:** no Claude attribution lines in this repo, ever. | Done. |
| Q3b | **RESOLVED:** `PROOFLAG_CONTACT_EMAIL` is set in gitignored `.env`; `.env.example` keeps a placeholder. UA = `Prooflag <email>`. | The address is never hard-coded and is **redacted** from logs, provenance rows, fixtures, reports and EVAL.md (redaction filter + a CI grep test). |

## 0b. Results log (F1–F5, 2026-11-13)

- **F1 done:** scaffold at `C:\dev\prooflag` (uv, ruff, mypy strict, pytest, CI, JSON logging, typed settings, injectable clock); 8 tests green. Note: uv cache must live off OneDrive-linked paths (`UV_CACHE_DIR=C:\dev\.uv-cache`, `UV_LINK_MODE=copy`).
- **F4a EDGAR (`docs/edgar-timing.md`):** `acceptanceDateTime` (UTC) matches the index-page "Accepted" stamp on 15/15 filings; the SGML header `ACCEPTANCE-DATETIME` is **ET, not UTC**; acceptance vs filing date diverge after 17:30 ET (Tesla 10-Q); www.sec.gov rejects UAs without an email-shaped contact, so live polling needs the user's `PROOFLAG_CONTACT_EMAIL`.
- **F4b Federal Register (`docs/fedreg-timing.md`):** 40/40 EOs appear on public inspection at least 12.8 h before publication (filed 11:15 or 08:45 ET, "special" filings); signing→publication median 5 days (max 48, reissue). **The weekly EO count is not knowable from the FR until ~3–6 days after the week ends**, so PI gives ≈1 day of lead; PI is `leading`, publication is `settling`.
- **F5 Strategy fixture (REAL, `fixtures/strategy_2026_05/`):** market found on Polymarket (resolved No, UMA proposed/disputed twice, volume ≈ $375.8M); rule text does not name SEC filings or say whether the deadline applies to the sale or its publication; 8-K `0001193125-26-249768` accepted 2026-06-01 08:00:16 ET (≈8 h after the deadline) reports 32 BTC sold May 26–31 at avg $77,135; YES price spiked 0.12 → 0.81 within 30 min of acceptance, then fell to 0.0005 by 17:30Z.
- **F3 done (`docs/model-smoke.md`):** Qwen3-8B and Llama-3.1-8B (Ollama, thinking off, schema-constrained): 12/12 schema-valid, all spans verbatim, identical repeats on an idle machine (not bit-exact once under concurrent load → replay uses cached outputs; never benchmark concurrently), ≈6 tok/s ≈ 30–45 s per call. Llama answered `ambiguous` on all 5 rules (possible over-abstention; n=5, unmeasured). Blob sha256s recorded in the doc. Qwen3-4B not needed.

- **S2 done (`docs/ingest.md`):** Kalshi + Polymarket ingest, tagger/clusters, versioned rules (`market_rule_changes`, A→B→A visible), sticky watch set, 5/30-minute per-venue snapshot cadence with backoff, history backfill, recorded fixtures (real responses incl. empty last pages, 422 on offset, gzip-406 on limit>50, 414/closed-lookup quirks), network blocked in tests. Findings: Kalshi volumes are **contracts** (dollar estimate = contracts × price; strict slice is **15 markets / 4 clusters**, not 19/4); Polymarket markets can have an empty `conditionId` (now skipped); non-Yes/No markets carry `yes_label`.

- **E1 EDGE STUDY done (`docs/edge-study.md`, inputs in `studies/e1/inputs/`, code `src/prooflag/edge/`):** verdict by the pre-registered rules = **NO SPEED EDGE** for weekly executive-order markets on the Federal Register path. 120/120 market results reproduced from FR data; 24 independent weeks usable (a market traded within 24 h before the posting; checker tightened this to the pre-registered wording, 29 under the looser first reading); in 22 of 24 the price was at 0.90+ about 2.9 days (median) BEFORE the public-inspection posting (move happens at signing/White House, 83% of weeks), so neither PI nor publication moves the price. Exceptions: the market's first two weeks (Oct/Nov 2025; in one a participant reacted 38 s after the posting). Primary P&L rests on 4/24 weeks (thin quotes) and is ≈ 0; the +$0.018 price-based figure is near-certain-Yes carry, not speed. Strategy (price-based, outside the verdict): the price rose ~5 min BEFORE the 8-K was accepted. IPO cluster: **Anthropic, PBC has publicly filed its S-1 (2026-10-26) with S-1/A and FWPs; markets did not move on those filings; effectiveness/424B pricing are pending and are the next live EDGAR test.** Other families: 0 resolved cases (INSUFFICIENT DATA). Build implication: no speed-driven evidence_gap on the FR path; weight toward ambiguity/deadline-risk/verification; measure the live Anthropic effectiveness/424B events with S3/S4 first. Backlog: make `ingest_series` read `/historical/markets`; Kalshi fee formula unverified.

## 1. Corrections to the brief (found in recon — treat as design changes)

1. **EDGAR Atom feed has no acceptance time** (only an unlabeled `updated` with offset). Atom is used for **discovery only**. Acceptance time comes from `data.sec.gov/submissions/CIK##########.json` → `filings.recent.acceptanceDateTime` (UTC `Z`; e.g. an 8-K accepted 13:00:15Z = 08:00 ET). Friday task: cross-check that field against a second source (filing index "Accepted" stamp or the `.txt` header) on ≥10 filings, old and new, before any deadline logic depends on it.
2. **EDGAR hours:** brief says 6 a.m.–10 p.m. ET; I could verify only 17 CFR 232.13 (5:30 pm cutoff for most forms; 10 pm for Forms 3/4/5, 144, 13D/G). Adaptive polling uses a configurable window, not a claimed fact.
3. **Kalshi real field names:** `rules_primary`, `rules_secondary`, `close_time`, `latest_expiration_time`, `expected_expiration_time` (no plain `expiration_time`), prices as `*_dollars`, counts as `*_fp`. List endpoint `GET /markets` (limit ≤1000, `cursor`; empty cursor = last page). Candlesticks: `/series/{series_ticker}/markets/{ticker}/candlesticks`, batch `/markets/candlesticks`. Base URL (`https://external-api.kalshi.com/trade-api/v2` vs `https://api.elections.kalshi.com/trade-api/v2`) is confirmed by a live call in the Friday slice-count script. Unauthenticated rate limits are unpublished → assume ≤ 5 req/s.
4. **Polymarket:** `GET gamma-api.polymarket.com/markets/keyset` (`after_cursor`, response `next_cursor`, `limit` 1–100, offset → 422). Prices are strings (`outcomePrices`, `volume`). Price history: `GET clob.polymarket.com/prices-history?market=<token_id>&interval=…&fidelity=…` (no auth, returns `{t,p}`).
5. **Ollama** `format` accepts a JSON schema; llama.cpp supports GBNF and `json_schema`. Qwen3 thinking mode vs constrained decoding must be tested Friday (disable thinking; confirm schema is obeyed).

## 2. Architecture

```
 Kalshi API ─┐                                   ┌──────────── EDGAR Atom (discovery)
 Polymarket ─┴─> ingest/ ──> markets ──> compiler/ ──> rule_specs      │
 (Gamma+CLOB)        │          │            ▲  (regex first, LLM 2nd, │
                     │          │            │   span verifier)        ▼
                     │          └──> linker/ (ticker→CIK) ──> watchers/sec ──> evidence locker
                     │                                                   │  (raw doc, sha256,
                     ▼                                                   │   acceptance vs fetch time)
                price_snapshots                                          ▼
                     │                                            evaluator/
                     │                                  LLM layer ──> deterministic gate
                     │                                                   │
                     └───────────────> signals/ (rules + dedupe + event log)
                                                   │
                         ┌─────────────────────────┼───────────────────────┐
                         ▼                         ▼                       ▼
                    web/ case files          notify/ desktop         outcomes ledger
                    (FastAPI+HTMX+SSE)       (win toast)             (+1h, +6h, settle)
 Cross-cutting: store/ (SQLite WAL, append-only), provenance, evals/, replay/, llm/ provider iface
```

### 2.1 SQLite schema (WAL, foreign keys ON; "append-only" tables get triggers that RAISE on UPDATE/DELETE)

| Table | Key columns | Notes / indices |
|---|---|---|
| `market_clusters` | PK `cluster_id`; label, rule (e.g. `issuer:anthropic_ipo`, `series:weekly_eo`), created_at | `markets.cluster_id` FK; evals, signals and the ledger aggregate **per cluster** so correlated markets (Anthropic/OpenAI IPO family) count once |
| `markets` | PK `(venue, market_id)`; cluster_id NULL, title, rules_text, rules_secondary, resolution_source, close_time_utc, status, raw_json_sha | first_seen_at, last_seen_at; idx `(status)`, `(close_time_utc)` |
| `market_versions` (append-only) | PK `(venue, market_id, rules_sha)`; rules_text, seen_at | detect rule edits; every spec points to a rules_sha |
| `market_tags` | PK `(venue, market_id, tag)`; reason, matched_span | why a market was tagged (sec/court/fed_register/press) |
| `price_snapshots` (append-only) | PK `(venue, market_id, outcome, ts_utc)`; price, volume, open_interest, source(`snapshot|history`) | idx `(venue, market_id, ts_utc)` |
| `artifacts` (append-only) | PK `sha256`; kind, byte_len, path, source_url, fetched_at_utc, accepted_at_utc NULL, accepted_at_source, normalizer_ver | the evidence locker index; files stored under `locker/aa/bb/<sha>` |
| `filings` | PK `(source, doc_id)` (`sec` accession or `fedreg` document_number); cik NULL, form/doc_type, filed_date, accepted_at_utc (SEC acceptance; FR public-inspection `filed_at`), published_at_utc NULL (FR official issue date), signing_date NULL, posted_kind(`accepted|public_inspection|published`), acceptance_cross_checked BOOL, primary_doc_sha, index_sha | idx `(cik, accepted_at_utc)`, `(source, doc_type)` |
| `entities` | PK `entity_id`; name, cik, ticker, link_status(`resolved|ambiguous|unresolved`), candidates_json, link_method | unresolved → review queue |
| `rule_specs` (append-only) | PK `spec_id`; market key, rules_sha, spec_json, valid BOOL, failed_checks_json, provenance_id | latest-valid view `v_current_spec` |
| `evaluations` (append-only) | PK `eval_id`; spec_id, filing accession, doc_sha, llm_output_sha, decision(`yes|no|unclear`), gate_json, final_decision, provenance_id | idx `(spec_id, accession)` UNIQUE with provenance |
| `llm_calls` (append-only) | PK `call_id`; input_sha, model_name, model_file_sha256, prompt_tmpl_sha, params_json, output_text, output_sha, latency_ms | cache key `(input_sha, model_file_sha256, prompt_tmpl_sha, params)` → replay reads these |
| `signals` | PK `signal_id`; type, market key, eval_id NULL (ambiguity/structural signals have none), spec_id, accession NULL, rules_sha, dedupe_key UNIQUE, variant, shadow BOOL, price_at_signal, status | idx `(type, market)` |
| `signal_events` (append-only) | `(signal_id|NULL, ts, event, reason)` | every fire AND every suppression with reason |
| `outcomes` | PK `(signal_id, horizon)`; horizon in `1h,6h,settle`; price, resolved_value | filled by outcome tracker |
| `reviews` | PK `(signal_id, reviewer, ts)`; label `correct|incorrect|ambiguous`, note | feeds gold sets |
| `provenance` (append-only) | PK `provenance_id`; input_hashes_json, model_name, model_sha256, prompt_sha, code_git_sha, dirty BOOL, created_at | referenced by every derived row |
| `poll_log` | `(source, ts, ok, latency_ms, items, err)` | health page |

All timestamps stored as UTC ISO-8601 plus the original zone string where relevant. Deadlines stored as `(deadline_utc, deadline_tz_original, deadline_text)`.

## 3. Modules and interfaces

Layout: `src/prooflag/{ingest,compiler,linker,watchers,evaluator,llm,signals,store,web,notify,evals,replay,config}/`; `tests/`, `fixtures/`, `scripts/`, `.github/workflows/ci.yml`, `pyproject.toml`, `.pre-commit-config.yaml`, `.env.example`.

- **config:** `Settings(BaseSettings)` from `.env`: contact email, db/locker paths, thresholds, rate limits, model name, `llm_endpoint`. No secrets committed.
- **store:** `Db` (WAL, `busy_timeout`), `Locker.put(bytes, meta) -> sha`, `Locker.get(sha)`, migration runner (plain SQL files, numbered), append-only triggers, `Provenance.record(...)`. Single writer discipline: all writes through one connection pool wrapper.
- **ingest:** `MarketSource` Protocol: `list_markets(since) -> Iterator[RawMarket]`, `price_history(market, start, end)`, `snapshot_prices()`. Impl: `KalshiSource`, `PolymarketSource` (keyset pagination). Common `RawMarket` normalizes to `markets` rows. `Tagger.tag(market) -> list[Tag(reason, span)]` with regex lexicon (EDGAR/SEC, 8-K/10-Q/10-K/Form 4/S-1, "docket", "court", "Federal Register", "press release"…). Stores everything; tags the subset.
- **compiler:** `RuleSpec` (Pydantic v2, strict, `extra=forbid`). Pipeline: `deterministic_extract(rules) -> PartialSpec` (dateparser/regex for deadlines with explicit tz handling, form-type lexicon, ticker/company regex) → `llm_fill(partial, rules)` for remaining fields → `SpanVerifier` (every field's `source_spans` must be an exact substring after canonical whitespace normalization; failure → field set to `ambiguous`/null and spec marked `valid=false` with reason) → `compile_market(market) -> RuleSpecRecord`. `deadline_applies_to` defaults to `ambiguous` unless a deterministic phrase rule or a verified LLM span supports otherwise.
- **linker:** `EntityLinker.resolve(name|ticker) -> LinkResult(status, cik, candidates)`. Source: SEC `company_tickers.json` cached locally with ETag/age; exact ticker match, then normalized-name exact match; fuzzy only produces *candidates* (never auto-accept). Multi-match or none → `ambiguous|unresolved` → review queue. `CourtLinker` Protocol stub (phase 2).
- **watchers:** `SourceWatcher` Protocol: `poll() -> list[DocumentEvent]` where `DocumentEvent(source, doc_id, entity_id, form, filed_date, accepted_at_utc, url)`. `SecWatcher`: Atom feed (discovery, latest 8-K/10-Q/4 pages) + per-watched-CIK `submissions` JSON (acceptance time, authoritative) → fetch primary doc → `Locker.put`. `RateLimiter` (token bucket ≤2 req/s global, shared by all SEC calls, stats exposed). Adaptive scheduler: fast (e.g. 60 s) in configured window (06:00–22:00 ET weekdays), slow (15 min) otherwise. Records `detected_at_utc − accepted_at_utc` lag. Declared UA from config; 429/403 → exponential backoff + health alarm. `CourtWatcher` interface only (first post-MVP milestone).
- **watchers/fedreg (MVP):** `FedRegWatcher` over the free `federalregister.gov/api/v1` API: (1) **published documents** (`/documents.json`, filter `type=PRESDOCU`/`conditions[presidential_document_type]=executive_order`, plus agency/rule filters for watched markets) with `publication_date`, `signing_date`, `executive_order_number`, `document_number`, `html_url`; (2) **Public Inspection** (`/public-inspection-documents.json` / `/public-inspection-documents/current.json`) giving `filed_at`, `publication_date` (scheduled), `filing_type`, `document_number`. Both stored as `filings`-style rows with `source='fedreg'`, `posted_kind in ('public_inspection','published')`, times in UTC plus the original ET string. Global limiter ≤ 1 req/s, declared UA. **Evidence semantics (to be confirmed by F4 and recorded in `docs/fedreg-timing.md`):** a public-inspection posting is a *leading* signal (document exists, scheduled to publish on date X); official publication (the issue date) is the *settling* evidence for markets that resolve on Federal Register publication/signing-date-as-recorded. The evaluator records which kind it matched; `evidence_gap` may use public-inspection only as `leading` (never as settled) unless F4 shows the rule text treats it as publication. Executive-order weekly markets: counting by `signing_date` as recorded in the FR.
- Shared `SourceWatcher` Protocol covers `SecWatcher`, `FedRegWatcher`; `CourtWatcher` later.
- **llm:** `LLMProvider` Protocol: `generate(prompt, schema, *, seed, temperature=0) -> LLMResult(text, model_name, model_sha256, latency)`. Impl `OllamaProvider` (primary; `format=<json schema>`, `think=false`, `options: seed, temperature 0, num_ctx`), `LlamaServerProvider` (OpenAI-compatible `response_format`/`json_schema`). Pinned model file sha256 recorded (hash of the GGUF blob). `CachedProvider` wraps with the `llm_calls` table (cache key above) → replay never re-infers. `FakeProvider` for tests.
- **evaluator:** `Evaluator.evaluate(spec, doc) -> Evaluation`. Text prep: one canonical `normalize_filing_text(html) -> str` (BeautifulSoup/lxml; strip tags, collapse whitespace, NFKC; function-versioned; its output is stored and hashed so the verbatim check is reproducible). Long docs: chunk by section/Item, score only chunks that pass lexical prefilter (entity+keywords), pass top-k to LLM. LLM layer returns schema (§5). Deterministic gate (§8). Any gate failure → `final_decision=unclear` + `failed_checks`.
- **signals:** `SignalEngine.process(evaluation, price_ctx) -> list[SignalEvent]` with dedupe key `(type, market, accession)`, cooldowns, config thresholds; writes `signal_events` for fires and suppressions. Gate flag `evidence_gap_enabled` is derived from the latest EVAL report, not hand-set.
- **web:** FastAPI + Jinja2 + HTMX, SSE endpoint `/events` for live updates. Pages: `/` (signals + queue counts), `/case/{signal_id}`, `/review`, `/markets`, `/health`, `/eval`. Binds 127.0.0.1 only. Source-span highlighting server-side (offsets verified, not regex re-search).
- **notify:** `Notifier` Protocol; `WindowsToastNotifier` (try `winotify`/`windows-toasts`, fall back to PowerShell BurntToast-free `System.Windows.Forms.NotifyIcon`, verify Friday which works) linking to `http://127.0.0.1:PORT/case/ID`; `NtfyNotifier` documented only.
- **evals:** gold fixtures loader, metrics, `EVAL.md` generator, labeling CLI/web helper, calibration bins.
- **replay:** `Replay.run(fixture) -> ReplayReport` using stored markets, locker documents, `price_snapshots`, and `llm_calls` cache, with a simulated clock injected through every time-dependent function (no `datetime.now()` in core logic; a `Clock` Protocol).

## 4. Local-model plan

Hardware tiers (sizes from Qwen3 GGUF repos; fit estimates are my inference):

| Tier | Model (GGUF Q4_K_M unless noted) | Disk | Use |
|---|---|---|---|
| 8 GB RAM, CPU | Qwen3-4B (2.5 GB) | 2.5 GB | fallback |
| **16 GB RAM, CPU (this machine, ~14.8 GB)** | Qwen3-8B Q4_K_M (5.0 GB) / Q5_K_M (5.85 GB) | 5–6 GB | **primary candidate** |
| 12 GB GPU | Qwen3-14B Q4_K_M (9 GB), tight | 9 GB | stretch |
| any | one non-Qwen ~7–9B instruct (e.g. Llama/Gemma/Phi class) | ~5 GB | control, to avoid single-family bias |

**Benchmark set (approved):** Qwen3-8B and one non-Qwen ~7–9B control only. Qwen3-4B is pulled and benchmarked only if 8B proves too slow.

Candidates are chosen by **gold-set results**, not preference. Benchmark harness (`scripts/bench_models.py`): for each candidate, run the **dev split only** of both gold sets (test split is reserved for the single frozen gating run) at temp 0, seed fixed; report field accuracy, evaluator precision/recall/abstain, schema-valid rate, median/p95 latency, tokens/s, RAM. Selection rule: highest evaluator Wilson-lower-bound precision, then lowest latency, subject to RAM < 10 GB. Note the iGPU is not assumed usable; Vulkan llama.cpp build is an optional Saturday experiment only.

Structured output: Ollama `format` = Pydantic `model_json_schema()` (flattened: no `$ref`/`oneOf` surprises; schemas kept simple and tested), thinking disabled; schema validity is still re-validated by Pydantic (belt and braces). Reproducibility: temp 0, fixed `seed`, pinned model file sha256 (`ollama show --modelfile` → blob digest, recorded per call), `num_ctx` fixed and recorded. Known caveat: bit-exact determinism across hardware/threads/Ollama versions is not guaranteed, so **replay is built on cached LLM outputs**, and "re-inference drift" is a separate reported metric, not a pass/fail test.

Friday tasks: `ollama pull` a text model; run 5-prompt smoke test for schema obedience with thinking off; record load time and tokens/s.

## 5. Prompt designs and schemas

### 5.1 Compiler (LLM fills only what deterministic extraction left open)

Output schema (strict):
```json
{
  "trigger": "string",
  "evidence_type": "sec_filing|federal_register|court_docket|press_release|other",
  "entity_name": "string|null",
  "acceptable_forms": ["string"],
  "deadline_text": "string|null",
  "deadline_applies_to": "publication|occurrence|ambiguous",
  "revisions_count": "boolean|null",
  "ambiguity_notes": ["string"],
  "headline_conflict": {"conflict": "boolean", "note": "string|null"},
  "source_spans": {
    "trigger": "string|null", "deadline": "string|null", "deadline_applies_to": "string|null",
    "evidence_type": "string|null", "entity": "string|null", "revisions_count": "string|null",
    "headline_conflict": "string|null", "acceptable_forms": ["string"]
  },
  "confidence": "number 0..1"
}
```
Deterministic post-processing: spans verified verbatim; `deadline_text` parsed by code into `deadline_utc` + original tz (naive times without tz → `ambiguous`, never assumed); `entity.cik` comes only from the linker, never the LLM; `compiler_confidence` = min(self-report, 1.0 if all spans verified else 0.0 cap) and is treated as uncalibrated until §6 calibration exists.

System prompt skeleton (hash recorded): "You extract fields from prediction-market resolution rules. Copy spans exactly from the text. If the rules do not say whether the deadline applies to when the event happens or when it is publicly reported by the source, answer `ambiguous`. Never infer a field you cannot quote. Output only JSON matching the schema."

Few-shot examples (templates; real ones are drawn from gold set once labeled, none invented as if real):
1. *Clear publication:* rules say "resolves Yes if an SEC filing **filed** on or before Dec 31, 2026 11:59 PM ET reports…" → `deadline_applies_to: publication`, span = "filed on or before Dec 31, 2026 11:59 PM ET".
2. *Clear occurrence:* "if the company **sells** any BTC between X and Y, as confirmed by any public source" → `occurrence`.
3. ***Ambiguous deadline (required):*** "Resolves Yes if Acme Holdings sells any Bitcoin by May 31, 2026 (11:59 PM ET). The primary resolution source will be Acme's official SEC filings." → `deadline_applies_to: ambiguous`; `ambiguity_notes`: ["Deadline attaches to the sale ('by May 31') but the resolution source is a filing that may be published after the deadline; text does not say whether post-deadline publication of a pre-deadline sale counts."]; spans quote both clauses. **Fictional entity** (Acme) on purpose: the Strategy rule text is a replay fixture and must never be a few-shot, and no real rule text is invented.
4. *Headline conflict:* the compiler also receives the market `title`; output field `headline_conflict: {conflict: bool, note: string|null, spans: [...]}`; gold set includes ≥5 cases (title says "by date" but rules measure publication, etc.).

**Stored `RuleSpec` = your schema plus additions:** `headline_conflict`, `rules_sha`, `deadline_utc`/`deadline_tz_original`, `deadline_basis` (`acceptance|filing_date|unspecified`), `compiler_provenance_id`, `valid`. In the *LLM output schema* `source_spans` is a **fixed-key object** (one optional string per field name, plus `trigger`, `deadline`, `deadline_applies_to`, `acceptable_forms` list-of-strings), not open-keyed, to stay compatible with constrained decoding; code reassembles it into the stored list-valued form.

**Eval hygiene:** few-shot rows are excluded from scoring; gold sets are split `dev` (≈60%, used for prompt/model tuning) and `test` (≈40%, touched only for the gating run); prompts are frozen (hash recorded) before the gating run; `EVAL.md` reports dev and test separately and states the residual optimism.

### 5.2 Evaluator

Few-shot output shapes are the schema below, e.g. `{"satisfied":"yes","quote":"<verbatim sentence>","quote_chunk_id":"c3","event_date_text":"May 28, 2026","event_date_quote":"<verbatim>","confidence":0.9,"reasoning":"..."}`; compiler examples 1–2 likewise are full JSON per the §5.1 schema, written when gold rows exist.

Input: the compiled spec (trigger, entity, forms, deadline semantics) + normalized doc chunks (with chunk ids). Output schema:
```json
{
  "satisfied": "yes|no|unclear",
  "quote": "string|null",
  "quote_chunk_id": "string|null",
  "event_date_text": "string|null",
  "event_date_quote": "string|null",
  "confidence": "number 0..1",
  "reasoning": "string (<=80 words)"
}
```
Prompt rules: answer `yes` only with a verbatim quote that itself states the triggering event; `no` only when the document affirmatively contradicts or the doc is plainly about the entity and states the opposite; everything else `unclear`. `event_date` is **not trusted**: it needs its own verbatim `event_date_quote` and a deterministic parse (code), else the date is treated as unknown and any occurrence-based check → `unclear`.
Few-shot (from gold set when labeled): (a) 8-K item 8.01 stating a purchase/sale with quote → yes; (b) an 8-K on unrelated topic → unclear (not "no"); (c) filing mentioning a *plan* to sell → unclear; (d) negation ("did not sell") → no.

## 6. Gold sets, labeling, metrics, gates

- **Fixtures (versioned):** `fixtures/gold/rules_v1.jsonl` (~40 rules → expected spec fields) and `fixtures/gold/pairs_v1.jsonl` (~25 `(rule, doc)` → yes/unclear/no with expected quote). Each row stores market id, rules_sha, doc sha, label, labeler, labeled_at, label_version. Documents are saved into `fixtures/` (small excerpts + sha) so tests need no network.
- **Selection:** `scripts/draft_gold.py` samples tagged markets stratified by venue/form type/deadline wording (force ≥8 ambiguous-deadline cases and ≥8 non-trivially-negative pairs). Pairs include **hard negatives** (right entity, wrong event; right event, wrong entity; late filing) because those are where precision fails.
- **Labeling panel (round 3; replaces human labeling).** Independent Claude Code subagents, caveman OFF: **Labeler A = Opus; Labeler B = Sonnet; Labeler C = Sonnet with the persona "skeptical securities lawyer" and shuffled item order.** They never see each other's outputs. **Haiku only fetches/prepares documents and runs mechanical checks; it never labels.** Qwen3-8B and Llama-3.1-8B (systems under test) never label. Each label = value + exact verbatim span(s)/quote + one-line reason. Pipeline: (1) deterministic check: every span must appear verbatim in the source after canonical normalization, else that label is invalid; (2) all three valid labels agree → accept, `labeler="ai_consensus"`; (3) disagreement or fewer than 3 valid → **Fable adjudicates** with all labels + reasoning; confident → `labeler="ai_adjudicated"`, else `status="contested"` (excluded from scoring and gates). Every individual label, the agreement pattern and adjudication notes are stored append-only with provenance (`labels_raw`, `label_consensus` tables). Gates use `ai_consensus + ai_adjudicated` only. `EVAL.md` must state the labels are **AI-consensus, not human-verified**, and report inter-labeler agreement (Wilson intervals), adjudication rate, contested rate, and how many **ambiguous-deadline** items were contested (same-family models share blind spots most there). `contested_items.md` is written for optional human glance. `prooflag label` CLI remains only as an optional override tool.
- **Labeling helper (optional override):** `prooflag label` CLI (and `/review` page): shows rule/document side by side, you fill fields; the first 15 spec labels are blind (no model prefill) to measure anchoring; later ones may show model output hidden behind a toggle. Every label is versioned; disagreements between model and you are logged.
- **Metrics (`EVAL.md`, generated, with git SHA + model hash + date):**
  - Compiler: per-field exact-match accuracy, with `deadline_applies_to` (3-class confusion matrix, abstain rate) and deadline (UTC equality) reported separately; span-verification pass rate.
  - Evaluator: precision, recall, abstain rate for `yes`; confusion matrix; **Wilson 95% intervals** (n is small, so no point estimates without intervals); deterministic-gate catch rate (how many LLM `yes` were downgraded, and whether correctly).
  - Calibration: reliability bins of confidence vs correctness, ECE, with the n-per-bin shown; confidence is **not** used for decisions beyond a threshold until bins show monotonicity.
- **Gates (enforced in code, read from latest `EVAL` JSON):**
  1. `evidence_gap` disabled unless, on the **test split**, evaluator `yes` precision ≥ 0.95 observed AND Wilson lower bound ≥ `gate_lb` (0.80) AND ≥ `gate_min_yes` (16) predicted-yes items (Q4). Expect it to stay disabled this weekend; that is the intended, honest outcome.
  2. `deadline_risk`/`ambiguity` need, on the rules **test split**, `deadline_applies_to` accuracy ≥ 0.85 with Wilson LB reported, and ambiguous-class recall ≥ 0.80 **only if ≥ 8 ambiguous test rows exist** (so the rules set is sampled with ≥ 20 ambiguous rows overall); otherwise these signals ship in "shadow mode" (logged and shown, no notification). Shadow mode is the expected weekend outcome.
  3. Any model or prompt change invalidates the gate until the evals are rerun (gate keyed on `(model_sha, prompt_sha)`).

## 7. Weekend schedule (1–2 h tasks, each with acceptance criteria)

**Order is conditional: Friday slice count decides everything below.**

**Friday night (approved order: F2 first, standalone, before any scaffolding; stop and report on NO-GO)**
- F1 (1.5 h, runs AFTER F2 passes GO): `git init` already done at `C:\dev\prooflag` (own repo); repo scaffold: `pyproject.toml` (uv; httpx, pydantic, apscheduler, fastapi, jinja2, hypothesis, respx), ruff, mypy strict config, pre-commit, pytest, CI file, `.env.example`, JSON logging setup (`prooflag.logging`). Commits in this repo: follow your jetbridge rule only if you say it applies; default per harness attribution. *Accept:* `ruff`, `mypy`, `pytest` all green on a smoke test; CI runs on push.
- F2 (2 h): **`scripts/slice_count.py`** (go/no-go thresholds per Q13): page through all open Kalshi and Polymarket markets (conservative rate limits), apply tagger, output a table `tag × venue × count × total volume/OI` + top 30 markets by volume. Confirms Kalshi base URL by live call. *Accept:* script runs end-to-end, writes `slice_report.md`. **GO/NO-GO (Q13): ≥ 20 live markets with an EDGAR/court/press-release source, each 24h volume ≥ $1,000 or OI ≥ $2,000.** If fewer, stop and propose widening scope (e.g. add Federal Register, official-statistic sources, earnings-release markets) before building further.
- F3 (1 h): Model setup: `ollama pull` Qwen3-8B and one non-Qwen ~7–9B control (size ≤ 6 GB); pull Qwen3-4B only if 8B is too slow; schema-obedience smoke test with thinking off; record tokens/s. *Accept:* 5/5 schema-valid outputs, model blob sha256 captured, latency table.
- F4 (1.5 h): **EDGAR + Federal Register timing validation.** (a) EDGAR: pull `submissions` JSON for 10+ filings (Strategy + others, old and new), cross-check `acceptanceDateTime` vs filing-index "Accepted" stamp → `docs/edgar-timing.md`. (b) FedReg: for ≥15 recent documents (incl. executive orders) compare Public Inspection `filed_at`/scheduled `publication_date` vs the official `publication_date`/issue; record lead time distribution, whether every EO appears on public inspection first, API fields available, and the signing-date → publication lag → `docs/fedreg-timing.md`. *Accept:* both notes written with concrete numbers and example document numbers; any doc lacking a public-inspection record is listed.
- F5 (45 min): Locate/archive the Strategy fixture (Q1) from Gamma closed markets + submissions JSON. *Accept:* real archived rule text, market id, filing accession and acceptance time saved to `fixtures/strategy_2026_05/`, or an explicit "NOT FOUND — synthetic" marker.

**Saturday**
- S1 (2 h; **done in round 3 → see git log**; then create the private GitHub repo and push): `store/` (schema, migrations, append-only triggers, locker, provenance, email redaction). *Accept:* tests prove UPDATE/DELETE on append-only tables fail; same bytes → same sha, one file; provenance rows complete.
- S2 (2 h): `ingest/` Kalshi + Polymarket + tagger + price snapshots/history. *Accept:* recorded-fixture tests pass; a live run stores ≥ 1 page of each; tags carry reason+span; cursor pagination tested incl. empty last page.
- **E1 EDGE STUDY (inserted after S2; runs BEFORE S3 and gates what is built next).** Question: do markets lag public documents enough to trade on? See §10d for scope, metrics and the pre-registered verdict rules. *Accept:* `docs/edge-study.md` with per-case table, lag distributions, honest n (clusters, not markets) with bootstrap uncertainty, the explicit answer to "do weekly-EO prices move at public inspection or only at official publication?", a verdict (NO SPEED EDGE / EDGE POSSIBLE / INSUFFICIENT DATA) computed by code from the pre-registered rules, and a build recommendation; study code unit-tested on recorded fixtures only.
- S3 (1.5 h): `linker/` + SEC ticker cache. *Accept:* unambiguous names resolve, multi-match/unknown go to review queue (property test: never returns a CIK when candidates ≠ 1).
- S4 (2 h): `watchers/sec` + rate limiter + acceptance-time capture + adaptive polling + health logging. *Accept:* live poll fetches a filing, stores acceptance vs fetch time, limiter test proves ≤ 2 req/s under load, lag metric recorded.
- S4b (2 h): `watchers/fedreg` (published + public inspection, ≤1 req/s, adaptive polling around typical posting times found in F4) + weekly-EO count evaluator helper (counts EOs by signing date from the FR per market week). *Accept:* recorded-fixture tests; live poll stores EO documents with signing/publication/public-inspection times; reproduces the true EO count for 3 past weeks vs the market's stated rule.
- S5 (2 h): `compiler/` deterministic extractor + LLM fill + span verifier + deadline tz parsing. *Accept:* hypothesis tests on tz/deadline parse (DST edges, naive times → ambiguous); span verifier rejects non-verbatim; compiles ≥ 90% of tagged markets to a valid or explicitly-invalid spec.
- S5b (1.5 h): `evals/` core + `scripts/draft_gold.py` + `prooflag label` CLI (needed before labeling): fixture loader, dev/test split by stable hash of market id, Wilson/ECE/confusion metrics, label CLI. *Accept:* metrics unit-tested against hand-computed values; CLI writes a valid JSONL row.
- **S6 (replaces S6a/S6b; starts as soon as S5/S5b finish, no scheduling around the user): AI consensus labeling panel**, run by subagents (caveman OFF), see §6 "Labeling panel". Produces `rules_v1.jsonl`, `pairs_v1.jsonl`, `labels_raw` (every individual label), `contested_items.md`. *Accept:* every label has verified verbatim spans; agreement/adjudication/contested stats written; `EVAL.md` labels section states "AI-consensus, not human-verified".
- ~~S6a (2 h): **Labeling session 1** (you):~~ (superseded) rules gold set (~40; ≥20 ambiguous-deadline across set, ≥5 headline-conflict; first 15 blind; **may sample closed/resolved markets** to reach the ambiguous quota). *Accept:* `rules_v1.jsonl` committed; first compiler accuracy report generated.
- ~~S6b~~ (superseded by S6; pairs need documents from S4 + specs from S5, so the panel's pairs pass runs after S4/S4b/S5).
- S7 (45 min, then runs overnight): `scripts/bench_models.py` kicked off on **dev split** of both sets for all candidates (resumable, cached in `llm_calls`). Needs a minimal evaluator LLM call, so S7 starts after a stub evaluator prompt exists (written in S6b downtime); the full evaluator + gate is U1.

**Sunday**
- U1 (2 h): `evaluator/` LLM layer + deterministic gate (a–d) + text normalizer. *Accept:* gate unit tests for each failure mode (non-verbatim quote, wrong form, wrong CIK, post-deadline acceptance, tz boundary cases) all downgrade to `unclear` with the failed check recorded.
- U2 (1.5 h): Read overnight benchmark, choose model by §4 rule, freeze prompts (hash), run the single **test-split gating run**, generate `EVAL.md`. *Accept:* `EVAL.md` with dev/test reported separately, intervals, calibration, confusion matrices; gate state written to the `EVAL` JSON.
- U3 (1.5 h): `signals/` engine (three rules, dedupe, cooldown, event log, gate reading `EVAL`). *Accept:* each suppression reason has a test; evidence_gap stays off if gate not met.
- U4 (2 h): `web/` case-file page, review queue, health page, SSE. *Accept:* case page shows every item in the brief's "Output: case files" list (market+rule text, spec with highlighted spans, doc with highlighted quote, every check pass/fail, acceptance vs deadline vs detection times, price at signal/+1h/+6h/settlement, provenance); manual click-through; labeling writes `reviews`.
- U5 (45 min): `notify/` desktop toast linking to case. *Accept:* toast appears on a test signal and the link opens the case.
- U6 (2 h): `replay/` + Strategy fixture replay + deterministic-replay test. *Accept:* replaying stored evidence twice yields byte-identical decisions; Strategy replay reports whether/when deadline_risk or ambiguity would fire and the lead time (if the real market was archived; otherwise run on the synthetic fixture and say so in the report).
- U6b (45 min): `prooflag run` (single APScheduler process: pollers, price snapshots, outcome tracker; **snapshot cadence: tagged markets every 5 min inside the EDGAR window, every 30 min otherwise**; the cadence job is built with S2 ingest so history accrues from Saturday) + CI check that fails on trading-endpoint strings (`/orders`, `create_order`, `place_order`) in `src/`. *Accept:* process starts, jobs register, CI check red on a planted string.
- U7 (1.5 h; the weekly report is the first thing cut): outcome ledger (`outcomes` filler via APScheduler at +1h/+6h/settlement using price snapshots/history), `prooflag weekly` report, README, `EVAL.md` final, handoff notes. *Accept:* ledger test with simulated clock fills the three horizons; fresh clone + `.env` → `pytest` green.

**Timing notes:** Friday tokens/s decides wall-clock for U2. Roughly 65 items × 3–4 models on CPU is hours, so the model benchmark runs **overnight Saturday→Sunday** via `scripts/bench_models.py` (resumable, results cached in `llm_calls`); Saturday S6 labeling produces the data it needs. APScheduler runs the pollers, outcome tracker and price snapshots in a single `prooflag run` process.

**Cut line / priority order (approved; ~1.5 weekends):** slice count → store/ingest/SEC watcher → compiler → labeling → evaluator + gate → replay → web case files → notifications/ledger/weekly report. Later items are cut first.

## 8. Signal rules and the deterministic gate

**Gate (all must pass, else `unclear` and the failed check is recorded):**
(a) `quote` appears verbatim in the stored normalized document (and `quote_chunk_id` exists); (b) deadline comparison in UTC using the timestamp the spec's `deadline_applies_to` demands: `publication` → acceptance datetime (and official filing date recorded alongside; if they straddle the deadline, result is `unclear`/ambiguity); `occurrence` → parsed `event_date` (verbatim-quoted, code-parsed) else `unclear`; `ambiguous` → evaluate **both** readings (acceptance time and parsed event date vs deadline); pass only if both pass, otherwise `unclear` with both results recorded; (c) `form ∈ acceptable_forms` (when specified; unspecified → recorded as "no constraint", not a pass); (d) filer CIK == entity CIK from linker (unresolved → fail).

**Signals:**
- `evidence_gap`: **only on markets with `yes_label == 'Yes'`** (plain yes/no; never Up/Down or named-outcome markets such as Anthropic/OpenAI; rule decided after S2, enforced and tested in U3) AND final decision `yes` AND gate all pass AND confidence ≥ `eg_min_conf` (default 0.8) AND price of the matching outcome ≤ `evidence_gap_max_price` (default 0.90, Q6) AND gate-enabled (§6). 
- `deadline_risk` (boolean conditions, all required; see Q11):
  - **Structural (live, pre-event):** spec `valid` AND `deadline_applies_to ∈ {publication, ambiguous}` AND `evidence_type == sec_filing` AND `0 < hours_to_deadline ≤ dr_hours` (default 72) AND no satisfying filing yet (latest evaluation for the spec is not `yes`) AND the form's legal filing-lag window extends past the deadline (lag table in config, **each entry verified against SEC rules before use**, e.g. 8-K 4 business days) AND market volume ≥ `dr_min_volume`.
  - **Post-hoc (replay/live after the fact):** uses `content_yes` = LLM `yes` with gates (a), (c), (d) passing and gate (b) excluded (the deadline gate would otherwise turn it into `unclear`); `content_yes`, `event_date` (verbatim-quoted, code-parsed) ≤ deadline, but acceptance time > deadline (the Strategy pattern) → fire with `variant=late_publication`.
  - No pre-filing occurrence data is used in the MVP; an occurrence feed (e.g. on-chain) is phase 2. The plan states honestly that live detection before the filing is *structural risk*, not evidence of occurrence.
- Defaults: `dr_min_volume = $1,000` 24h volume, `amb_min_volume = $1,000`, `amb_days = 14`, all config.
- `ambiguity`: spec has `deadline_applies_to == ambiguous` or a headline/rule conflict note, on a market with volume ≥ `amb_min_volume` and ≤ `amb_days` to close. Fires once per `(market, rules_sha)`.
- All signals: dedupe on `(type, market, accession|rules_sha)`; cooldown per market (default 6 h); every fire or suppression writes `signal_events` with a reason code (`below_conf`, `price_too_high`, `gate_disabled`, `duplicate`, `cooldown`, `gate_fail:<check>`).

## 9. Testing plan and fixtures

- `pytest` with recorded HTTP (via `respx`/`pytest-httpx`; network blocked by a conftest autouse fixture). `hypothesis`: deadline parse, tz conversion, DST transitions, acceptance-vs-deadline comparison, linker invariants, span verifier (substring with whitespace normalization), rate limiter.
- **Replay determinism test:** run pipeline on stored evidence with the `llm_calls` cache twice with a fixed injected clock; assert identical decisions and provenance-input hashes. Separate non-failing report: re-inference drift.
- `mypy --strict` on `store`, `compiler`, `evaluator`, `signals`, `llm`; ruff everywhere; pre-commit; GitHub Actions: ruff, mypy, pytest (no model needed, `FakeProvider`).
- **Fixture list (additions for FR/EO):** FR `documents.json` page with ≥3 executive orders (signing vs publication dates), a public-inspection record for one of them, an EO signed Friday and published the next week, a week with zero EOs, a correction/rescission document, a document on PI that is withdrawn; weekly-EO market rules (Kalshi) with different week windows.
- **Fixture list:** Kalshi market page (SEC rule, plain rule, empty last cursor); Polymarket keyset pages (incl. 422 offset response); prices-history sample; EDGAR Atom page; `submissions` JSON (Strategy); company_tickers sample (with ambiguous names); 8-K docs: positive, unrelated, plan-only, negation, amended (8-K/A); Strategy May-2026 case (real if archived, else synthetic, labeled); acceptance-after-5:30pm filing; DST-boundary deadline; naive-timezone deadline; non-verbatim quote case.

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Too few markets in slice | F2 go/no-go; widen scope before building |
| SEC throttling/UA block | ≤2 req/s global limiter, declared UA, backoff, health alarm, cache everything |
| Atom feed lacks acceptance time / field semantics wrong | submissions JSON as authority, F4 cross-check, record both times |
| Local model too slow/inaccurate on CPU | lexical prefilter + chunking, 4B/8B benchmark, cache by input hash, abstain by default |
| Constrained decoding quirks (thinking mode, `$ref`) | flat schemas, thinking off, Pydantic revalidation, Friday smoke test |
| Timezone/DST bugs | UTC internally, original tz stored, hypothesis tests, naive times → ambiguous |
| Rule edge cases (amendments, multiple filers, 8-K/A, "reported by" wording) | form lexicon includes amendments flag; unclear on mismatch; gold hard negatives |
| Venue API changes / unpublished limits | recorded fixtures + contract tests, schema-tolerant parsing logged not crashed, conservative rates, base URL verified live |
| Data gaps (no price history) | own snapshots from day 1; replay uses whatever exists and reports gaps |
| Small gold sets → false confidence | Wilson intervals, minimum n, gate on lower bound, labeled "n=…" everywhere |
| LLM self-confidence uncalibrated | not used for decisions beyond a threshold until calibration shown |
| OneDrive vs SQLite WAL | Project at `C:\dev\prooflag`, data in gitignored `data\` (Q9) |
| Strategy fixture unverifiable | Q1; synthetic fixture labeled as such; no false claims in docs/EVAL |
| Public inspection does not reliably precede publication / fields differ (e.g. special filings, EOs posted same day) | F4 measures lead time distribution; PI is a *leading* signal only; spec records which posting kind satisfied the rule; documented in `docs/fedreg-timing.md` |
| Federal Register API changes / rate limits | recorded fixtures + contract tests, ≤1 req/s, schema-tolerant parsing |
| Weekly EO "week" boundaries and timezone (signing date as recorded vs publication date) | rule compiler extracts week window; counting uses FR `signing_date`; hypothesis tests on week edges in ET |
| Correlated markets inflate apparent accuracy | `cluster_id`; metrics and gates computed per cluster, n_clusters reported |
| Scope creep to trading | no order code anywhere; CI grep check for trading endpoints |

## 10a. Round 3 decisions (applied throughout)

1. **Strategy fixture = REQUIRED NEGATIVE TEST (named acceptance test `test_strategy_2026_05_never_evidence_gap`, owned by U1/U3/U6):** on `fixtures/strategy_2026_05/` the pipeline must **never emit `evidence_gap`**; it must emit **`ambiguity` pre-filing** and **`deadline_risk` with `variant=late_publication` post-filing**. **Why:** the YES price spiked from ≈0.12 to ≈0.81 within 30 minutes of the 8-K's acceptance (2026-06-01 08:00:16 ET, ≈8 h after the 23:59 ET May 31 deadline) before the market resolved No; the filing "satisfied" the content of the rule, but the rule never said the deadline applied to occurrence rather than publication, so a naive evidence_gap would have recommended buying YES into a loss. Therefore **evidence_gap is suppressed whenever `deadline_applies_to` is `ambiguous`** (suppression reason `gate_disabled:ambiguous_deadline`), independent of the precision gate. U1 asserts the gate result, U3 asserts the signal set, U6 asserts the replay timeline.
2. **Compiler runs two models:** Qwen3-8B and Llama-3.1-8B both compile every rule; if their `deadline_applies_to` disagree, the stored value is forced to `ambiguous` and the disagreement (both outputs) is recorded in `rule_specs.failed_checks_json`/provenance. The **evaluator uses a single model**, chosen by the gold-set benchmark (§4).
3. **Benchmarks and any heavy model job run alone, enforced by a lock file** (`data/model.lock`, exclusive create; second job exits with a clear message). Cached-output replay never needs the lock.
4. **GitHub:** after S1, create a private repo `prooflag` and push (via `gh` if authenticated; otherwise the exact commands are given to the user). No secrets are ever committed (`.env` ignored; email redaction test).
5. **Machine/hosting:** laptop may stay on overnight for benchmarks; live polling runs only while it is on; no cloud hosting.
6. **Contact email:** only in `.env`; never hard-coded; redacted from logs, provenance, fixtures, reports, EVAL.md.
7. **Labeling:** AI consensus panel replaces manual S6a/S6b (see §6). Benchmark timing: the panel runs as soon as S5/S5b (and S4/S4b documents) are ready; the overnight model benchmark starts when `rules_v1`/`pairs_v1` dev splits exist and the model lock is free, i.e. it is no longer tied to a human labeling session.

## 10b. Scope adjustments (round 2): eval priorities and clustering

- **Eval/feedback priority:** the weekly Executive Order series (Kalshi "How many Executive Orders will Trump sign this week?", plus the second-term total) is the primary source of frequent, objectively resolvable cases: gold pairs and the live outcome ledger lean on it first. Gold rules/pairs sampling quota: ≥ 30% of pairs from FR/EO markets; EDGAR hard negatives still required.
- **Clustering:** every market gets a `cluster_id` by rule (same issuer IPO family, same weekly series *per week*, same event). Metrics (precision, hit rate, lead time) report **n_markets and n_clusters**; gates (§6) are evaluated on clusters, not markets. The Anthropic/OpenAI IPO markets are one cluster (`issuer_ipo_family`); a cluster counts once as a win/loss.
- **Meaningful filter (tightened):** `vol24 >= 1000` or ≥ 5 trades in 24h; Kalshi OI alone with zero volume excluded; Polymarket liquidity never counts. Applied in the slice report and in default watch lists; the full unfiltered classified list stays in `data/slice_classified.json`.
- **MVP sources:** EDGAR + Federal Register. Courts: first post-MVP milestone (interface already defined).

## 10c. Strategy acceptance test (named, required)

`test_strategy_2026_05_never_evidence_gap` — inputs: `fixtures/strategy_2026_05/` (rule text, 8-K, EDGAR acceptance time, price history). Asserts, per stage: **U1** gate: `deadline_applies_to == ambiguous`, publication-basis check fails (acceptance 2026-06-01T12:00:16Z > deadline 2026-06-01T03:59:00Z), `content_yes` true; **U3**: signals emitted ⊆ {`ambiguity`, `deadline_risk(late_publication)`}, `evidence_gap` suppressed with reason `gate_disabled:ambiguous_deadline`; **U6**: replay timeline shows `ambiguity` before 2026-06-01T12:00:16Z and `deadline_risk` after it, and no `evidence_gap` at any time including the 12:30Z price spike (YES ≈ 0.81).

## 10d. Round 5 decisions (after S2)

1. **Watch set = curated allow-list**, append-only (`watch_allowlist`: venue, market_id / series_ticker / event_id, reason, reviewer, added_at; revocations are new rows). Seeded from the hand-reviewed DOC_SETTLED (strict) list, the whole `KXEOWEEK` series, and the Strategy fixture market. **Regex matches only enter a candidate review queue (`watch_candidates`), never auto-watched.** Sticky `watched` from S2 is reset and recomputed from the allow-list.
2. **evidence_gap only on `yes_label == 'Yes'` markets** (U3 rule, see §8).
3. **Backlog:** database retention/compaction (market_versions grows by every distinct rule text; 134k markets ≈ 370 MB; plan: compress/prune `market_raw` blobs of settled untagged markets, vacuum, optional archive of settled non-watched markets).
4. **E1 EDGE STUDY runs before S3** (below).

### E1 — Edge study scope, metrics, pre-registered verdict rules (written BEFORE looking at results)

**Cases (cluster = independent unit):** weekly executive-order markets (`KXEOWEEK`, settled weeks; one cluster per week), Anthropic/OpenAI IPO family (one cluster), Federal Register EO/emergency markets, court markets with docket timestamps (where resolvable), and the Strategy case (EDGAR 8-K). Only resolved cases with a documented t_doc can be measured; unresolved ones are listed with "no event yet".
**Document times:** EDGAR `acceptanceDateTime`; Federal Register public-inspection `filed_at` (t_pi) AND official publication (t_pub = 06:00 ET on the publication date; an approximation, the issue is posted that morning); signing date (date only). For weekly EO the settling document for threshold N is the (N+1)-th EO signed in the week (by FR `signing_date`), so t_pi/t_pub are those of that EO.
**Per case (Yes-implied, i.e. the document proves Yes):** price at t_doc (last trade if present else bid/ask mid, stale quotes older than 30 min = no quote); time from t_doc until the price first reaches ≥0.90 and ≥0.95 (negative = the price led the document); price at t_doc + 1 min / 15 min / 1 h / 6 h and achievable gross edge (1 − yes_ask); after-fee P&L of the naive rule "buy YES at the yes_ask at t_doc + 2 min, hold to settlement" per 100 contracts using the venue fee schedule (Kalshi: taker fee = ceil-to-cent(0.07 × C × P × (1−P)) unless the series says otherwise; Polymarket: market `feeSchedule`); whether the market resolved as the document implied. No-implied cases are reported separately (t_doc = end of week) and do not enter the verdict.
**Aggregation:** per-week mean over that week's markets, then statistics over weeks: n_weeks, median and p25/p75 of lag, share of weeks with price already ≥ 0.90 at t_pi, mean P&L per contract with a 95% bootstrap CI over weeks (10,000 resamples, seed 1). Correlated clusters (IPO family) count once.
**Key question:** for weekly-EO markets does the price move at public inspection or only at official publication? Measured as the share of the final jump (from the week-start price to 1.0) already realized at t_pi and at t_pub, and as |price move| in [t − 5 min, t + 15 min] around each.
**Verdict rules (fixed now):** primary family = weekly EO (t_pi basis).
- **INSUFFICIENT DATA** if usable weeks (≥1 Yes-implied market with prices around t_pi) < 10.
- **NO SPEED EDGE** if share(price ≥ 0.90 at or before t_pi) ≥ 70% OR the UPPER 95% CI bound of mean after-fee P&L per contract ≤ $0.02.
- **EDGE POSSIBLE** if the LOWER 95% CI bound of mean after-fee P&L per contract > $0 AND median lag ≥ 5 minutes AND usable weeks ≥ 10.
- Anything else: **INSUFFICIENT DATA (inconclusive)**.
The doc also states what each verdict implies for what to build next (speed/evidence_gap focus vs ambiguity/risk-tool focus vs FedReg-first).

### E1 Amendment A (2026-11-14, written after the data-availability probes and BEFORE any price data was analysed)

Probes showed the first draft of the rules was wrong or incomplete in these ways. These supersede the E1 text above where they conflict; the original text is kept for the record.

1. **Deciding document.** Threshold N is provable once N+1 distinct in-week EOs have appeared. t_pi (and t_pub) for a market are therefore the **(N+1)-th smallest posting time** among the in-week EOs, not those of the (N+1)-th EO by signing date. In-week = FR `signing_date` inside the market's period (period and N are **parsed from the rule text**, since older tickers have no threshold suffix). EOs are de-duplicated by `executive_order_number` (a reissue such as `R1-...` keeps the earliest posting). **Validation:** the computed Yes/No must match the venue's recorded `result` for each market, and each Yes market's close date should equal the deciding EO's publication date; mismatches are listed, not hidden.
2. **Price data.** Settled-market candles are sparse: every hour with trades has a candle (verified 95/95 hours on three markets) and hours without activity have none. So (a) **traded prices and times come from the trades endpoint** (second-level timestamps, sizes; live + `/historical/trades`), (b) bid/ask come from candles with carry-forward, (c) a quote older than 24 h is "no quote" (pre-registered; markets here are thin). Candle price = last trade in the period, never invented.
3. **Verdict precedence and size.** NO SPEED EDGE takes precedence over EDGE POSSIBLE. EDGE POSSIBLE additionally requires **dollar capacity**: the after-fee profit a taker could have captured by buying all Yes volume that traded in [t_pi + 2 min, market close] at prices below 0.95 (Σ count × (1 − price) − fees) must have a per-week **median ≥ $10**; if the edge criteria hold but capacity is below that, the verdict is NO SPEED EDGE ("edge, if any, is not tradable at size") and the capacity numbers are reported. P&L alone is not evidence: buying Yes after the Federal Register proves Yes is profitable by construction whenever the price is below 1.
4. **Third answer to the key question.** The price may move at signing, before either posting. For each Yes case the first trade at ≥ 0.90 is bucketed: before the signing date / signing day before t_pi / between t_pi and t_pub / after t_pub / never before close. The answer to "PI or publication?" is the distribution over these buckets.
5. **Market close.** Yes markets close hours after publication (about 10:00-10:30 ET on publication day, per the rules the market can close early when the outcome is determined). Offsets beyond the close are reported as N/A, not zero. t_pub = 06:00 ET on the publication date is an assumption and labelled as such.
6. **Full history:** nested `/events` markets (30) plus `/historical/markets` (93, settled before the 2026-09-13 cutoff). (Correction: the earlier "30 settled weeks" in `docs/ingest.md` was 30 markets in only 8 weeks; the S2 series ingest never reached the older weeks.)
7. **Public-inspection times** are fetched per document from the FR API for every EO in range; if missing, the number after `?` in `public_inspection_pdf_url` is a fallback (verified once: it equals the posting time of `2026-22051`).
8. **Reproducibility:** study inputs (events, markets, trades, candles, EO documents) are committed under `studies/e1/inputs/`; `docs/edge-study.md` is regenerated offline from them.
9. **Fees.** Polymarket (docs.polymarket.com/trading/fees): taker fee = C × rate × p × (1 − p) using the market's `feeSchedule` (the Strategy market: rate 0.04, taker-only); makers pay nothing. **Kalshi's formula could not be verified from its docs** (fee pages rate-limited); assumption: taker fee = ceil-to-cent(0.07 × fee_multiplier × C × p × (1 − p)) per order (the series reports `fee_type: quadratic, fee_multiplier: 1`). Every Kalshi P&L is reported under that assumption AND fee-free as a sensitivity. The Strategy case has no historical bid/ask (CLOB price only): its P&L is **price-based** and is excluded from the pooled verdict.

## 11. Phase 2 roadmap

**First post-MVP milestone: CourtListener** (docket-ID linker, authenticated polling ~5,000 q/h; 20 strict court/agency events in the slice, mostly SCOTUS cert grants and PACER-resolved rulings), then the items below. Original list:
CourtListener watcher (docket-ID linker, authenticated polling ~5,000 q/h, bounded); Federal Register and newsroom/press-release watchers; occurrence-side data (e.g. on-chain feed for Strategy-type markets) so `deadline_risk` can fire before publication; Polymarket US ingester once docs verified; automated weekly digest delivery of the ledger summary (the `prooflag weekly` command itself ships in U7); API/MCP tool exposing `get_case`, `list_signals` read-only; public dispute archive of resolved-ambiguity cases; optional self-hosted ntfy push.

## 11b. Review focus (inputs most likely to bite; each gets a test in the owning task)

1. Filing accepted 5:30–10 pm ET: acceptance date vs official filing date differ → both stored, deadline check names the basis (S4/U1).
2. Amended filings (8-K/A), multiple filers/co-registrants, wrong-entity mentions → gate (c)/(d) → `unclear` (U1).
3. Naive or ambiguous timezone/DST deadlines, "end of day", "midnight" → `ambiguous`, never assumed (S5).
4. Rule edited after compile (new `rules_sha`) → old spec/signals invalidated, recompile (S2/S5).
5. Huge or malformed filing HTML / exhibits-only filings / empty feed pages → normalizer and chunker degrade to `unclear`, never crash the poller (S4/U1).

## 12. Verification of the plan itself (what "done" looks like at weekend end)

1. `pytest`, `ruff`, `mypy --strict` (core) green locally and in CI.
2. `python scripts/slice_count.py` produces `slice_report.md`.
3. `EVAL.md` exists with intervals, confusion matrices, calibration, model hash, git SHA.
4. Replay twice → identical decisions (test passes).
5. A synthetic or real Strategy fixture replays to a documented signal outcome.
6. Local web app on 127.0.0.1 shows a case file with every item listed in the brief; desktop toast opens it.
7. `evidence_gap` gate shows disabled/enabled with the metric that decided it.
