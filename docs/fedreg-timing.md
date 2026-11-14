# Federal Register timing check (F4b)

Script: `scripts/timing_fedreg.py`. Raw output: `data/fedreg_timing.json` (gitignored). Run date: 2026-11-13.
Sample: the 40 most recent executive orders (EO 14388 .. 14438), published 2026-04-09 to 2026-10-28.
API: `https://www.federalregister.gov/api/v1`, free, no key, requests at 1 req/s.

## Endpoints and fields

- Published documents: `/documents.json` (filter `conditions[presidential_document_type][]=executive_order`)
  and `/documents/{document_number}.json`. Fields used: `document_number`, `executive_order_number`,
  `signing_date`, `publication_date`, `html_url`, `public_inspection_pdf_url`, `citation`,
  `correction_of`, `executive_order_notes`. `signing_date` is available from the single-document endpoint
  (and via `fields[]` on the list endpoint); it was absent from the default list fields.
- Public inspection: `/public-inspection-documents/current.json` (today's desk; carries
  `special_filings_updated_at` and `regular_filings_updated_at`) and, per document,
  `/public-inspection-documents/{document_number}.json`. Fields: `filed_at` (ET with offset),
  `filing_type` (`special` or `regular`), `publication_date` (scheduled), `pdf_updated_at`,
  `last_public_inspection_issue`, `editorial_note` (withdrawals), `num_pages`.

## Findings (n = 40 EOs)

1. **40/40 EOs have a public-inspection record**, and the PI `publication_date` equals the official
   `publication_date` for all 40.
2. **Public inspection precedes official publication by at least 12.8 h** (measured to 00:00 ET of the
   publication date; the issue itself appears on that morning, so the true lead is slightly larger).
   Distribution: 12.8 h (35 docs), 15.2 h (3 docs), 60.8 h (2 docs, weekend gaps). **Zero negatives.**
3. **EOs are filed as `special` filings** (39 of 40; 1 `regular`) at **11:15 ET** (37 docs) or **08:45 ET**
   (3 docs): the day before publication, except across weekends.
4. **Signing to publication lag: median 5 days, min 3, max 48.** The 48-day case is a reissued/corrected
   document (`R1-2026-03829`, EO 14388: signed 2026-02-20, published 2026-04-09). So the official EO
   count for a signing week is **not knowable from the FR until roughly 3 to 6 days after the week
   ends**; public inspection shortens that by about one day only.
5. **Postings can be withdrawn** after going on public inspection (`editorial_note` on `2026-23084`, a
   non-EO notice), so a PI posting is not final until publication.

## Rules adopted

- Public inspection is a **leading** signal (document exists, scheduled publication date D). The
  **settling** evidence for FR-publication markets is official publication. For weekly EO markets resolved
  by "signing date as recorded in the Federal Register", the settling source is the published FR record's
  `signing_date`. A PI document already shows the EO text and signing date, so it gives about 13 h to
  2.5 days earlier detection, but it stays `leading` unless a market rule says posting counts.
- Poll PI around the observed filing slots (08:45 ET, 11:15 ET, 16:15 ET) plus a slow background poll.
- Weekly-EO markets: always fetch the full document to read `signing_date`; never use `publication_date`
  to place an EO in a week.
- Open question for S4b: confirm that each Kalshi weekly EO rule counts by signing date (the snippet says
  "signing date as recorded in the Federal Register"); compile the week window per market and test on
  3 past weeks.
