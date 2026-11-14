# Strategy / MicroStrategy "sells any Bitcoin by May 31, 2026?" fixture (REAL, archived 2026-11-13)

Verified from primary sources (not only a secondhand description):

- Polymarket event slug `microstrategy-sell-any-bitcoin-in-2025` ("MicroStrategy sells any Bitcoin by ___ ?");
  market conditionId begins `0x3733a1b647` (see `polymarket_market_may31.json`). Question: "MicroStrategy sells
  any Bitcoin by May 31, 2026?". Resolved **No** (`outcomePrices ["0","1"]`), `closedTime` 2026-06-04 00:34:19+00,
  `umaResolutionStatuses` ["proposed","disputed","proposed","disputed"], lifetime volume about $375.8M.
- Full rule text: resolves Yes "if MicroStrategy sells any of its Bitcoin by 11:59 PM ET on the date
  specified in the title"; "The primary resolution source for this market will be information from MSTR and
  on-chain data, however a consensus of credible reporting will also be used." The `resolutionSource` field is
  empty. The rule names neither SEC filings nor whether the deadline applies to the sale or to its publication.
- EDGAR: Strategy Inc (CIK 0001050446) 8-K accession `0001193125-26-249768`, items 7.01/8.01, accepted
  **2026-06-01T12:00:16Z = 08:00:16 ET**, about 8 h after the 2026-05-31 23:59 ET deadline. Text: "BTC Update ...
  During Period May 26, 2026 to May 31, 2026: BTC Sold 32, aggregate sale price $2.5 million, average sale price
  $77,135". Document sha256 `e5e7942f2637dcf577ad71e4dcf8b476321055a4d9c175214e7dbe5221bc009a`
  (`8k_20260601_mstr-20260530.htm`).
- Price (YES token, CLOB `prices-history`): about 0.12 until 2026-06-01 11:30Z, 0.35 at 12:00Z and 0.81 at
  12:30Z right after the filing was accepted, down to about 0.41 by 17:00Z, then 0.0005 by 17:30Z (see
  `yes_price_history_*.json`). The reported UMA dispute is consistent with the `disputed` statuses;
  the lawsuit was not independently verified here.
- Other Strategy filings from 2026-05-22 to 2026-06-08 are in `edgar_submissions_window.json`.

Use: replay fixture (`deadline_risk` `late_publication` variant, and `ambiguity`). Never a few-shot example.
