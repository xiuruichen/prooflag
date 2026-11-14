# SEC watcher (S4) and entity linker (S3): design notes

Code: `src/prooflag/watchers/`, `src/prooflag/linker/`, `src/prooflag/sec_client.py`. Run the watcher with
`uv run python scripts/run_sec_watcher.py` (needs `PROOFLAG_CONTACT_EMAIL` in `.env`; Ctrl+C to stop).

## What it records

| Field | Source | Meaning |
|---|---|---|
| `accepted_at_utc` | submissions JSON `acceptanceDateTime` (UTC) | EDGAR's acceptance time: authoritative (docs/edgar-timing.md) |
| `filed_date` | submissions JSON `filingDate` | EDGAR's official filing date; can differ from the acceptance day |
| `date_basis_differs` | computed | filing date != ET calendar date of acceptance (e.g. accepted 20:35 ET Nov 10, dated Nov 12) |
| `detected_at_utc` | our clock at first sight | when WE saw it; `detected - accepted` is the detection lag (`detection_lags()`) |
| `discovered_via` | `submissions` or `atom` | which channel saw it first |

## Rules

1. **Baseline.** The first successful poll of a CIK stores its history with `detected_at_utc` NULL and emits no events:
   history is not a detection. Later polls emit one `NewFiling` per new accession.
2. **Submissions JSON is authoritative; Atom is discovery only.** The Atom "latest filings" page (per form: `EFFECT`,
   `424B4`, `424B3`, `424B1`, `8-A12B`) has no labelled acceptance time. An Atom-discovered filing of a watched,
   baselined CIK is stored with `accepted_at_utc` NULL and filled in when the submissions JSON catches up (keeping the
   earlier `detected_at_utc`); it never produces a second event.
3. **Accession is the filing identity.** A filing can have several filers (co-registrants); it is stored once, keyed by
   accession, and not re-emitted when a second watched CIK lists it.
4. **Evidence.** The primary document goes into the evidence locker (`kind sec_primary_doc`) with the EDGAR acceptance
   time stored separately from our fetch time. Filings without a primary document (e.g. `EFFECT` notices) and 404s are
   skipped without error; documents above 25 MB are not stored.
5. **Politeness and privacy.** At most 2 requests/second (global limiter). The User-Agent `Prooflag <contact>` is sent
   only to sec.gov / data.sec.gov (`SecClient`); Kalshi, Polymarket and the Federal Register get a generic UA. A 403 is
   raised with a hint to set the contact email. 429 honors `Retry-After`; 5xx is retried with backoff.
6. **Cadence.** Fast (default 30 s) in the EDGAR window (06:00-22:00 ET, weekdays), slow (15 min) otherwise. After a failed
   poll a source backs off 2, 4, 8 ... minutes (capped at its normal interval) independently of other sources; `run_due()`
   never raises. Health is in `poll_log` (`sec:submissions:<cik>`, `sec:atom:<form>`).
7. **Watch list.** `watch_ciks` is append-only (reason + reviewer, revocable), seeded from `config/watch_ciks.json`
   (Anthropic, PBC for E2; Strategy Inc for the fixture issuer).

## Entity linker (S3)

`EntityLinker.resolve(name | ticker)` returns a 10-digit CIK only when exactly one company matches (reviewed alias, exact
ticker, or exact normalized name). Several companies, or a ticker and a name pointing at different companies, are
`ambiguous`; no match is `unresolved` with fuzzy candidates for review. Results are recorded in `entities`; the review
queue is everything not resolved. The SEC file is cached under `data/` with `If-Modified-Since` revalidation (the file has
no ETag) and a stale-cache fallback when the SEC is unreachable. Findings from the real file (10,404 rows): tickers are
unique per CIK, 6 normalized names map to two CIKs (e.g. Rio Tinto PLC / LTD), 1,432 CIKs have several tickers (share
classes), Anthropic, PBC (`ANT`) is present, OpenAI is absent (stays unresolved), and "MicroStrategy" (a former name) is not
in the file, so it is a reviewed alias in `config/entity_aliases.json`.

## Known limits

- The submissions JSON `filings.recent` array holds about the last 1,000 filings; older pages (`filings.files`) are not read.
- Atom polling cannot see a filing that appears and is superseded between ticks; the submissions poll is the safety net.
- Federal holidays are not special-cased in the cadence (a few extra requests on closed days).
