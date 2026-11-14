# Market ingest (S2): venue facts, rules, and decisions

Code: `src/prooflag/ingest/`. Recorded fixtures: `tests/fixtures/ingest/` (real responses, recorded with
`scripts/record_ingest_fixtures.py`; tests never touch the network, enforced by `tests/conftest.py`).
Live validation: `scripts/run_ingest_once.py`.

## Venue facts (verified live, 2026-11-13)

| Topic | Kalshi | Polymarket |
|---|---|---|
| Catalog | `GET /events?status=open&with_nested_markets=true&limit=200`, `cursor` (empty = last page). Multivariate/combo markets are NOT in `/events`; they appear in `/markets?mve_filter=only` (`mve_collection_ticker`, `KXMVE*`) and are dropped by `is_multivariate`. | `GET /events/keyset?closed=false&active=true&archived=false&limit=50`, `after_cursor` / `next_cursor` (absent = last page). `offset` is rejected: HTTP 422 `offset is not allowed on keyset endpoints`. `limit` above 50 is served gzip-only (HTTP 406 `gzip_required` without `Accept-Encoding: gzip`); we use 50. |
| Sports | `event.category == "Sports"` (event level; the market has no category, the event has `series_ticker`). | event tag labelled `Sports`; combo markets: `comboStatus == "enabled"`. |
| Units | `volume_24h_fp`, `volume_fp`, `open_interest_fp` are **contracts**, not dollars (docs: "in contracts"). Dollar volume is estimated as contracts x last price (falling back to bid/ask mid; else unknown). | `volume24hr` is USD. `liquidityNum` is order-book liquidity (never open interest). |
| Fields as strings | prices are dollar strings (`"0.1200"`) | `outcomePrices`, `outcomes`, `clobTokenIds` are JSON-encoded strings. |
| Lookups | `GET /markets?tickers=a,b,...` (300 tickers worked; we batch 100; no limit applied when `tickers` is the only filter). | `GET /markets?condition_ids=...`: ~40 ids per call (150 gives HTTP 414). **Closed markets are silently absent unless `closed=true` is also queried**; we run both. |
| Settlement | market `status` active/closed/determined/finalized, `result` yes/no. | `closed=true`, `outcomePrices` ["0","1"], `umaResolutionStatuses` (e.g. proposed, disputed). Markets past `endDate` but not closed (awaiting resolution) are kept as status `past_end`. |
| History | `/series/{series}/markets/{ticker}/candlesticks?start_ts&end_ts&period_interval` (minutes); max 5000 candles per request (HTTP 400 beyond). Candles with no trades have **no trade price** (50 of 72 in the fixture): stored as NULL, bid/ask close kept. | `clob /prices-history?market=<yes token>&startTs&endTs&fidelity`: range limit between 15 and 20 days (HTTP 400 `interval is too long`); we chunk at 14 days. |
| Series (weekly EO) | `series_ticker` lives on the event: weekly executive orders = `KXEOWEEK` (event `KXEOWEEK-26NOV14` = week ending 2026-11-14), second term = `KXEOTRUMPTERM`. `/events?series_ticker=KXEOWEEK&status=settled` returns 54 settled weeks with `result`. | n/a |

## Decisions (calls I made; change them in `config.py` or here)

1. **"Meaningful" = estimated 24h dollar volume >= $1,000.** Kalshi OI alone with zero volume never counts and
   Polymarket liquidity is stored separately (`markets.liquidity_usd`) and never counted. Correction to the
   earlier slice report: the slice scan compared Kalshi *contracts* to $1,000. With a dollar estimate the strict
   DOC_SETTLED slice is **15 markets in 4 clusters** (was 19 in 4): cheap Kalshi weekly-EO brackets trade many
   contracts at a few cents.
2. **Primary eval source:** `KXEOWEEK` markets are tagged `weekly_eo` + `primary_eval`, watched regardless of
   volume, one cluster per week (`weekly_eo:YYYY-MM-DD`), and settled weeks are ingested for backfill/evals.
3. **Correlated clusters:** any Anthropic/OpenAI IPO market on either venue -> `issuer_ipo_family`; otherwise the
   cluster is the event (bracket markets count once).
4. **Watched is sticky.** A market becomes watched when it is a document-family candidate and meaningful (or
   primary eval). It stays watched when volume dips. It leaves the snapshot set only when settled, after a final
   snapshot with status/result is stored. `past_end` (unresolved) markets stay in the set.
5. **FOMC/Fed-rate markets** are tagged `fomc` and never watched (excluded from the document-settled count).
6. **Rule versioning:** `rules_sha = sha256(title \x1f rules_primary \x1f rules_secondary)` over the exact text
   (no normalization; spans are verified against the stored text later). `market_versions` holds each distinct
   text once; `market_rule_changes` (append-only) logs every transition, so an A -> B -> A revert is visible.
   Snapshot refreshes also carry the rules, so a silent edit is caught between catalog passes.
7. **Snapshots:** `price_snapshots` stores yes bid/ask/last (the ask is what a buyer pays, last trade is stale on
   thin markets), `volume` = 24h USD estimate, `open_interest` = Kalshi contracts. History rows leave `volume`
   NULL (per-period contracts are not comparable). Existing timestamps are never replaced.
8. **Cadence:** 5 min inside the EDGAR window (06:00-22:00 ET, weekdays, configurable), 30 min otherwise; hourly
   catalog. US federal holidays are not special-cased. One `run_due()` tick per minute decides what is due
   (`jobs.schedule`); the full `prooflag run` process is assembled in U6b.
9. **Privacy:** Kalshi/Polymarket requests use the generic UA `Prooflag/0.1 (research; read-only)`; the SEC contact
   email is never sent to venues (tested). A bounded request rate (4 req/s shared) is used because unauthenticated
   limits are unpublished.
10. **Writes:** catalog pages are written in batches (500) inside one transaction with a savepoint per market, so
    one bad market is counted and skipped. The raw venue JSON goes to the evidence locker only on first sight or a
    rules change, and only for tagged markets (prices change every pass and are not archived as blobs).

11. **Unidentifiable markets are skipped, never merged.** Live run: 53 Polymarket markets (e.g. the Kraken IPO
    bracket) have an empty `conditionId`; keyed on `''` they collapsed into one row and produced 52 bogus rule
    changes. They are now skipped and counted (`CatalogStats.errors`). Any other malformed market is skipped and
    counted too, and unparsable dates become `None`; one bad market can no longer abort a pass.
12. **Non-Yes/No Polymarket markets** (e.g. "Anthropic or OpenAI IPO first?", outcomes Anthropic/OpenAI): bid,
    ask and last refer to the FIRST outcome. `markets.yes_label` records which outcome that is, and `token_ids['yes']`
    aliases its token so history backfill works. Downstream logic (evidence_gap) must only treat `yes_label == 'Yes'`
    markets as plain yes/no.
13. **Scheduling is per venue with backoff.** Catalog (hourly) and snapshots (5/30 min) each keep their own
    schedule per venue; after failures a venue is retried after 2, 4, 8 ... minutes (capped at its normal interval),
    so an outage neither hammers the dead venue nor repeats the healthy one. `run_due()` never raises. A failed
    history backfill for a market is not retried for an hour.

14. **Correction (found in E1): series history coverage.** Earlier text said the S2 series ingest reaches "30
    settled weeks" of `KXEOWEEK`. That was 30 *markets* in only 8 weeks: `/events` nests markets only for
    recently settled events. Older markets live behind `/historical/markets?series_ticker=` (93 more, settled
    before the exchange cutoff, 2026-09-13), with `/historical/trades` for their trades. `KalshiSource` now has
    `iter_historical_markets`, `iter_trades` and `all_trades` (live + historical, de-duplicated by trade id); the
    E1 study uses them. `IngestService.ingest_series` still reads only nested events: **backlog** (make it
    include historical markets so the local DB holds the full weekly-EO history).

## Known limits

- Tagging is regex-over-rule-text (recall oriented). Kalshi "court" matches are noisy (elections, certified
  results); the watch rule needs a document-family tag AND meaningful volume, which removes most of it, but a
  hand-reviewed allow-list (as in the slice review) is not applied automatically.
- A Kalshi lookup lacks event context, so a market with an empty `title` falls back to the event title only
  during catalog passes; this could register a one-off false rule change. Not observed.
- History backfill runs once per watched market. Live markets are covered going forward by snapshots.
