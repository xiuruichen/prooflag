# Fixtures and third-party data

Tests use recorded, small samples of public data. Nothing here is user data: Polymarket wallet fields are stripped at ingest, and no account identifiers are stored.

| Location | Source | Fetched | Terms |
|---|---|---|---|
| `tests/fixtures/sec/`, `fixtures/strategy_2026_05/` (8-K, submissions) | SEC EDGAR | 2026-11-13 | US government work, public domain. Fair-access policy applies to fetching |
| `tests/fixtures/edge/`, `studies/e1/inputs/fr_eos.json.gz` | Federal Register API | 2026-11-13/14 | US government work, public domain |
| `tests/fixtures/ingest/kalshi_*`, `studies/e1/inputs/kalshi_*` | Kalshi public API | 2026-11-13/14 | **Not verified**: Kalshi terms returned HTTP 429 when checked. The API docs say use is governed by the Kalshi Developer Agreement and state no redistribution rule |
| `tests/fixtures/ingest/poly_*`, `tests/fixtures/ingest/clob_*`, `fixtures/strategy_2026_05/polymarket_*`, `fixtures/strategy_2026_05/yes_price_*`, `studies/e1/inputs/ipo_cluster.json.gz`, `strategy_prices.json.gz` | Polymarket Gamma, CLOB and data APIs | 2026-11-13/14 | Polymarket Terms of Use (polymarket.com/tos, effective 2026-08-11) restrict scraping and commercial redistribution of Data. They do not address small research samples. **Gray area; no legal review done** |

If you are a venue and want any sample removed, open an issue and it will be replaced with synthetic data.

To refresh fixtures: `scripts/record_ingest_fixtures.py` and `scripts/edge_fetch.py`.
