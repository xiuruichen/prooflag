# EDGAR timing check (F4a)

Script: `scripts/timing_edgar.py`. Raw output: `data/edgar_timing.json` (gitignored). Run date: 2026-11-13.
Sample: 15 filings (forms 4, 8-K, 10-Q) across 5 filers (Strategy, Apple, NVIDIA, Tesla, Coinbase),
filed 2026-10-02 to 2026-11-12. **Limitation:** only the most recent filings (the `recent` array) were
sampled; no pre-2026 filings, so behavior across older years is unverified.

## Findings

1. **`submissions` JSON `acceptanceDateTime` is authoritative and in UTC.** For 15/15 filings,
   converting it to America/New_York equals the "Accepted" stamp on the filing index page to the
   second (delta 0 s), including across the EST/EDT boundary (Oct vs Nov).
2. **The SGML header `<ACCEPTANCE-DATETIME>` (in `<accession>.txt`) is in New York local time, not UTC.**
   It differs from the API UTC value by exactly 18000 s (EST) or 14400 s (EDT). Never parse the header
   value as UTC.
3. **Acceptance time and official filing date can differ.** Tesla 10-Q `0001628280-26-066775`:
   accepted 2026-10-21 20:12:41 ET, `filingDate` 2026-10-22 (accepted after 17:30 ET, so dated the next
   business day). Form 4s accepted at 18:58 ET and 18:30 ET kept the same-day filing date (Form 4
   cut-off is 22:00 ET). Consequence for Prooflag: store both, and name which one the deadline check used.
4. **Atom feed has no acceptance time** (research finding, 2026-11-13); it is used for discovery only.
5. **User-Agent:** `www.sec.gov` rejects UAs with no email-shaped contact (HTTP 403 on
   `company_tickers.json`, the Atom feed and Archives pages); `data.sec.gov/submissions` accepted a bare
   UA. Live polling therefore requires `PROOFLAG_CONTACT_EMAIL` set to a real contact in `.env`.
   This check used a placeholder-shaped contact at about 1.5 requests/s for about 40 requests in total.

## Rules adopted

- `accepted_at_utc` := `acceptanceDateTime` (UTC). Cross-check against the index page stamp stays a
  sampled test, not a per-filing runtime fetch.
- Never trust the `.txt` header time as UTC.
- `filingDate` is stored separately as `filed_date`; the deadline basis is recorded as `acceptance` or `filing_date`.
