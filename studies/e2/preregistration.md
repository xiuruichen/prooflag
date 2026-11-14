**Written 2026-11-14 (about 04:30 UTC), BEFORE any of the events below have occurred.** At that time EDGAR shows for Anthropic, PBC (CIK 2130357, ticker ANT) a public S-1 (2026-10-26), S-1/A (Nov 2, Nov 10) and FWPs (latest 2026-11-12 11:08Z), and **no** `EFFECT`, `424B*` or `8-A12B` filing. Nothing here may be changed after either event occurs; deviations must be added as a dated amendment.

**Question.** Do the Anthropic IPO markets move before, or within about 5 minutes of, the EDGAR filings that settle them? (E1 found the answer was yes for weekly executive orders and for Strategy; E2 tests the EDGAR-first thesis on the one liquid cluster where it can still be tested live.)

**Events (the settling documents).**
- **A: the SEC notice of effectiveness** (form `EFFECT`) for Anthropic's S-1. For the Kalshi "officially announce an IPO" markets (resolve Yes if the SEC declares the S-1 effective OR the IPO is priced OR shares list) A alone makes Yes certain.
- **B: the final pricing prospectus**, the first of `424B4` / `424B1` / `424B3` accepted after A. It fixes the offering price and share count, which settle the valuation, amount-raised, percent-sold and lead-underwriter markets.
- **t_doc** = the filing's EDGAR `acceptanceDateTime` (UTC, from the submissions JSON; verified authoritative in docs/edgar-timing.md).
- Observation window: until 2026-12-31. If an event has not happened by then it is reported as "not observed".

**Markets (selection fixed now).** Every market in cluster `issuer_ipo_family` whose title names Anthropic, binary with `yes_label == 'Yes'` (Polymarket) or a standard Yes/No Kalshi market, open at t_doc, and **document-implied** for the event: for A, the Kalshi series `KXIPOANTHROPIC` ("announce an IPO by DATE") markets whose date is on or after t_doc; for B, the markets that settle on the final prospectus (valuation / raise / % sold / lead-left bank). Whether a market is document-implied is decided from its rule text BEFORE looking at prices. **Usable** = at least 10 trades (Kalshi) or at least 20 distinct price points (Polymarket) in the 24 h before t_doc. The direction of each market (Yes or No) is its recorded resolution, read after settlement (B) or implied by A (A).

**Price data.** Kalshi: all trades (exact times and sizes). Polymarket: CLOB history at 1-minute fidelity fetched within the retention window (fetch within 3 days of the event), plus our own snapshots (bid/ask/last, 5-minute cadence inside the EDGAR window). Fees: Kalshi taker fee = round_up-to-cent(0.07 x multiplier x C x p x (1-p)) per order, using each series' `fee_type` (non-standard types handled explicitly); Polymarket per the market's `feeSchedule`. Every P&L is shown with and without fees.

**Definitions (per usable market).** p_dir(t) is the last trade price at or before t (stale beyond 24 h = no price), as seen in the resolved direction (price if Yes, 1 - price if No). p0 = p_dir(t_doc - 60 min), pA = p_dir(t_doc), p5 = p_dir(t_doc + 5 min).
- **moved_by_5min** = p5 >= 0.90, OR (p0 < 0.90 AND (p5 - p0) / (1 - p0) >= 0.50), i.e. the market already reflects the outcome, or at least half of the remaining distance was covered, within 5 minutes of the filing (this includes moves BEFORE the filing).
- Also reported: pA >= 0.90 (already priced at the filing), time from t_doc to the first sustained p_dir >= 0.90 (all later trades stay at or above it), p_dir at t_doc + 1 min / 15 min / 1 h / 6 h, and capacity = after-fee profit available by buying in trades below 0.95 in [t_doc + 2 min, t_doc + 24 h or market close].

**Event signal (min 3 usable markets, else INSUFFICIENT for that event).**
- **DEAD-signal** if share(moved_by_5min) >= 70%.
- **ALIVE-signal** if share(moved_by_5min) <= 30% AND the median time to first sustained 0.90 is >= 5 minutes AND capacity for the event >= $100 (higher than E1's $10 because these markets are liquid).
- Otherwise **INCONCLUSIVE**. Markets of one event are one correlated cluster; n here is 1 per event type, so results are reported per event and never pooled into a significance claim.

**Overall verdict.**
- **SPEED THESIS DEAD**: at least one event is DEAD-signal and none is ALIVE-signal.
- **MIXED**: one event DEAD-signal, the other ALIVE-signal (speed matters only for that document type).
- **SPEED THESIS ALIVE (provisional)**: at least one event ALIVE-signal and none DEAD-signal. Provisional because it rests on one issuer.
- **INSUFFICIENT DATA**: neither event observed by 2026-12-31, or no event has 3 usable markets.
- Anything else: **INCONCLUSIVE**.

**Consequence of SPEED THESIS DEAD (decided in advance).** Prooflag's MVP becomes an ambiguity + deadline-risk + verification tool: descope speed-related work (fast-polling priority, evidence_gap UI emphasis); keep EDGAR and Federal Register watchers for authoritative timestamps and verification only.

**Also logged (not part of the verdict).** (1) Our watcher's detection lag for each filing (detected_at minus accepted_at); if it exceeds 60 s the event is flagged "not actionable by our system". (2) The earliest timestampable earlier public signal we can find for each event (press report, company statement, exchange notice), with source and URL, in `studies/e2/signals.md`, written after the fact on a best-effort basis; a signal that precedes t_doc by 5 minutes or more AND coincides with a price move is noted next to the result.

**Limitations stated in advance.** One issuer, two events, one correlated cluster per event; hindsight in market-direction assignment is limited to reading settled outcomes; Polymarket price history has no bid/ask; the 5-minute and 70%/30% thresholds are conventions fixed here, not estimated.
