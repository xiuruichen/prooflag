# E1 Edge study: do prediction markets lag public documents enough to trade on?

Generated offline from `studies/e1/inputs/` (fetched 2026-11-14T04:03:51.682907+00:00, code `8894f5fcc3`) by `scripts/edge_study.py`. Pre-registered rules: PLAN.md section 10d (E1 + Amendment A). The verdict below is computed by code from those rules; the commentary at the end is hand-written and post-hoc.

## Verdict (weekly executive-order markets, public-inspection basis)

### **NO SPEED EDGE**

- price already >= 0.90 at the posting in 92% of weeks (>= 70%)
- upper 95% bound of mean after-fee P&L $0.007 <= $0.02

| quantity | value |
|---|---|
| independent units (weeks) usable | 24 (rule: >= 10) |
| Yes-implied markets in those weeks | 51 |
| share of weeks with price already >= 0.90 at the posting | 92% (Wilson 95% [74%, 98%]; rule: >= 70% means no edge) |
| after-fee P&L per contract, buy YES at ask t+2 min (weeks) | mean $0.0023, 95% CI [$0.0000, $0.0070] |
| weeks with a usable ask (P&L defined) | 4 of 24 (most thin markets have no quote within 24 h of the posting; the primary P&L rests on these weeks only) |
| same, fee-free sensitivity | mean $0.0025, 95% CI [$0.0000, $0.0075] |
| sensitivity: buy at LAST TRADE price (no spread) at t+2 min, after fees (24 weeks) | mean $0.0179, 95% CI [$0.0101, $0.0276] |
| lag: first sustained 0.90 minus posting, minutes (weeks) | median -4206.3 [p25 -5240.7, p75 -2570.7] (n=24) (rule: median >= 5 min) |
| median per-week capacity (after-fee profit available below 0.95) | $0.00 (rule: >= $10) |
| upper-bound floor for 'no edge' | $0.02 |

Fee assumption: Polymarket formulas are from docs.polymarket.com/trading/fees; **Kalshi's fee formula could not be verified** (fee pages rate-limited). Assumed taker fee = ceil-to-cent(0.07 x multiplier x C x p x (1-p)) per order, multiplier from the series (quadratic, x1); the fee-free row bounds the effect.

## Data and validation

- Resolved KXEOWEEK markets analysed: 120 (yes 60, no 60); unparsed rules: 0 [].
- Federal Register executive orders: 112 (signing >= 2025-08-01); public-inspection time source: API 112, URL-timestamp fallback 0, missing 0.
- **Method validation:** computed result (count of in-window EOs by FR signing date, de-duplicated by EO number) equals the venue's recorded result for 120/120 markets.
- Yes market close date minus deciding-EO publication date (days): median 1.0 [p25 0.0, p75 4.0] (n=51).
- Exclusions from the Yes-implied sample: not Yes-implied: 57; market closed before the public-inspection posting: 8; exactly-N rule: validated only: 4.

## Key question: public inspection or official publication?

First sustained trade at or above 0.90, relative to the deciding EO's signing date (00:00 ET), public-inspection posting and publication (06:00 ET, assumed). Weeks use the modal bucket of their markets.

| first SUSTAINED trade >= 0.90 occurs ... | markets | % | weeks (modal) | % |
|---|---|---|---|---|
| before_signing | 4 | 8% | 2 | 8% |
| signing_to_pi | 45 | 88% | 20 | 83% |
| pi_to_pub | 2 | 4% | 2 | 8% |
| after_pub | 0 | 0% | 0 | 0% |
| never | 0 | 0% | 0 | 0% |

Share of the final jump (week-start price to 1.0) already realized at the posting: public inspection median 0.97 [p25 0.95, p75 0.98] (n=35); official publication median 0.96 [p25 0.95, p75 0.98] (n=18).

Last traded price relative to the public-inspection posting:

| offset from posting | last traded price (median [p25, p75], n) | N/A (market closed) | no trade in 24 h |
|---|---|---|---|
| +1 min | median 0.990 [p25 0.990, p75 0.990] (n=36) | 0 | 15 |
| +15 min | median 0.990 [p25 0.990, p75 0.990] (n=36) | 0 | 15 |
| +1 h | median 0.990 [p25 0.990, p75 0.990] (n=37) | 0 | 14 |
| +6 h | median 0.990 [p25 0.990, p75 0.990] (n=30) | 0 | 21 |

Relative to official publication:

| offset from posting | last traded price (median [p25, p75], n) | N/A (market closed) | no trade in 24 h |
|---|---|---|---|
| +1 min | median 0.990 [p25 0.990, p75 0.990] (n=18) | 5 | 28 |
| +15 min | median 0.990 [p25 0.990, p75 0.990] (n=18) | 5 | 28 |
| +1 h | median 0.990 [p25 0.990, p75 0.990] (n=18) | 5 | 28 |
| +6 h | median 0.990 [p25 0.990, p75 0.990] (n=14) | 16 | 21 |

Lag of first sustained 0.90 versus publication (minutes, weeks): median -6084.5 [p25 -6549.2, p75 -4897.6] (n=16).

## Dollar capacity

After-fee profit a taker could have captured by buying all YES volume that traded below 0.95 after posting + 2 min: median $0.00 per week, total $10,841.91 over 24 weeks.

## Per-week table (public-inspection basis)

| week | markets | price led? | median lag 0.90 (min) | mean P&L/contract | capacity |
|---|---|---|---|---|---|
| KXEOWEEK-25DEC20 | 1 | yes | -2626.1 | n/a | $0.00 |
| KXEOWEEK-25NOV08 | 1 | no | 681.1 | n/a | $830.33 |
| KXEOWEEK-25NOV29 | 1 | yes | -2571.6 | n/a | $0.00 |
| KXEOWEEK-25OCT19 | 1 | no | 0.7 | n/a | $10,011.58 |
| KXEOWEEK-26APR04 | 2 | yes | -4828.8 | n/a | $0.00 |
| KXEOWEEK-26APR18 | 1 | yes | -5090.2 | n/a | $0.00 |
| KXEOWEEK-26AUG08 | 3 | yes | -5407.0 | n/a | $0.00 |
| KXEOWEEK-26AUG15 | 1 | yes | -4165.4 | n/a | $0.00 |
| KXEOWEEK-26AUG29 | 3 | yes | -2595.8 | n/a | $0.00 |
| KXEOWEEK-26FEB14 | 1 | yes | -107.7 | n/a | $0.00 |
| KXEOWEEK-26FEB21 | 1 | yes | -2488.9 | n/a | $0.00 |
| KXEOWEEK-26JAN17 | 1 | yes | -2568.1 | n/a | $0.00 |
| KXEOWEEK-26JUL25 | 2 | yes | -4070.4 | n/a | $0.00 |
| KXEOWEEK-26JUN06 | 3 | yes | -8195.8 | n/a | $0.00 |
| KXEOWEEK-26JUN27 | 3 | yes | -3572.4 | n/a | $0.00 |
| KXEOWEEK-26MAR07 | 1 | yes | -5250.4 | n/a | $0.00 |
| KXEOWEEK-26MAR14 | 1 | yes | -5510.3 | n/a | $0.00 |
| KXEOWEEK-26MAR21 | 2 | yes | -4342.2 | n/a | $0.00 |
| KXEOWEEK-26MAR28 | 2 | yes | -4345.7 | n/a | $0.00 |
| KXEOWEEK-26MAY02 | 2 | yes | -6766.1 | n/a | $0.00 |
| KXEOWEEK-26MAY23 | 2 | yes | -2531.5 | n/a | $0.00 |
| KXEOWEEK-26MAY30 | 2 | yes | -5361.2 | n/a | $0.00 |
| KXEOWEEK-26OCT03 | 3 | yes | -2784.9 | 0.0000 | $0.00 |
| KXEOWEEK-26OCT10 | 1 | yes | -3896.6 | n/a | $0.00 |
| KXEOWEEK-26OCT17 | 1 | yes | -5200.5 | 0.0093 | $0.00 |
| KXEOWEEK-26OCT24 | 2 | yes | -4872.7 | 0.0000 | $0.00 |
| KXEOWEEK-26SEP05 | 2 | yes | -7378.6 | 0.0000 | $0.00 |
| KXEOWEEK-26SEP12 | 2 | yes | -2658.6 | 0.0000 | $0.00 |
| KXEOWEEK-26SEP19 | 3 | yes | -5383.1 | 0.0000 | $0.00 |

## Weeks where the price did NOT already lead the posting

| week | median lag 0.90 (min) | capacity (after-fee profit below 0.95) |
|---|---|---|
| KXEOWEEK-25NOV08 | 681.1 | $830.33 |
| KXEOWEEK-25OCT19 | 0.7 | $10,011.58 |

2 of 24 weeks. These carry all of the dollar capacity in the sample (the per-week median is $0). They are listed so the heavy tail is visible; with n this small it cannot be called a pattern, and the chronology is noted in the interpretation.


## Per-market table

| market | t_pi | price@pi | lag 0.90 (min) | bucket | ask@pi+2m | P&L/contract | close-pub days |
|---|---|---|---|---|---|---|---|
| KXEOWEEK-25DEC20 | 2025-12-17 16:15Z | 0.980 | -2626.1 | signing_to_pi | n/a | n/a | 0 |
| KXEOWEEK-25NOV08 | 2025-11-06 13:45Z | 0.890 | 681.1 | pi_to_pub | n/a | n/a | 0 |
| KXEOWEEK-25NOV29 | 2025-11-26 16:15Z | 0.990 | -2571.6 | signing_to_pi | n/a | n/a | -1 |
| KXEOWEEK-25OCT19 | 2025-10-17 15:15Z | 0.820 | 0.7 | pi_to_pub | n/a | n/a | -1 |
| KXEOWEEK-26APR04-0 | 2026-04-02 15:15Z | 0.990 | -2856.2 | signing_to_pi | n/a | n/a | 5 |
| KXEOWEEK-26APR04-1 | 2026-04-08 15:15Z | 0.990 | -6801.5 | signing_to_pi | n/a | n/a | 1 |
| KXEOWEEK-26APR18-0 | 2026-04-21 15:15Z | 0.990 | -5090.2 | before_signing | n/a | n/a | 1 |
| KXEOWEEK-26AUG08-0 | 2026-08-05 15:15Z | 0.990 | -2731.5 | signing_to_pi | n/a | n/a | 1 |
| KXEOWEEK-26AUG08-1 | 2026-08-10 15:15Z | 0.990 | -5431.4 | signing_to_pi | n/a | n/a | 11 |
| KXEOWEEK-26AUG08-2 | 2026-08-10 15:15Z | 0.990 | -5407.0 | signing_to_pi | n/a | n/a | 11 |
| KXEOWEEK-26AUG15-0 | 2026-08-13 15:15Z | n/a | -4165.4 | signing_to_pi | n/a | n/a | 9 |
| KXEOWEEK-26AUG29-0 | 2026-08-28 15:15Z | n/a | -2595.8 | signing_to_pi | n/a | n/a | 4 |
| KXEOWEEK-26AUG29-1 | 2026-09-01 15:15Z | n/a | -7052.7 | signing_to_pi | n/a | n/a | 2 |
| KXEOWEEK-26AUG29-2 | 2026-09-02 15:15Z | 0.900 | -743.8 | signing_to_pi | n/a | n/a | 1 |
| KXEOWEEK-26FEB14 | 2026-02-13 16:15Z | 0.920 | -107.7 | signing_to_pi | n/a | n/a | -3 |
| KXEOWEEK-26FEB21 | 2026-02-20 16:15Z | 0.990 | -2488.9 | signing_to_pi | n/a | n/a | -2 |
| KXEOWEEK-26JAN17 | 2026-01-16 16:15Z | 0.950 | -2568.1 | signing_to_pi | n/a | n/a | -3 |
| KXEOWEEK-26JUL25-0 | 2026-07-22 15:15Z | 0.990 | -2616.3 | signing_to_pi | n/a | n/a | 0 |
| KXEOWEEK-26JUL25-1 | 2026-07-28 15:15Z | 0.990 | -5524.5 | signing_to_pi | n/a | n/a | 4 |
| KXEOWEEK-26JUN06-0 | 2026-06-04 15:15Z | 0.990 | -2859.9 | signing_to_pi | n/a | n/a | 7 |
| KXEOWEEK-26JUN06-1 | 2026-06-09 12:45Z | 0.990 | -8197.9 | signing_to_pi | n/a | n/a | 2 |
| KXEOWEEK-26JUN06-2 | 2026-06-09 12:45Z | 0.990 | -8195.8 | signing_to_pi | n/a | n/a | 2 |
| KXEOWEEK-26JUN27-0 | 2026-06-24 15:15Z | 0.990 | -3572.4 | before_signing | n/a | n/a | 0 |
| KXEOWEEK-26JUN27-1 | 2026-06-24 15:15Z | 0.990 | -2597.6 | signing_to_pi | n/a | n/a | 0 |
| KXEOWEEK-26JUN27-2 | 2026-06-29 15:15Z | 0.990 | -5293.0 | signing_to_pi | n/a | n/a | 9 |
| KXEOWEEK-26MAR07-1 | 2026-03-10 15:15Z | n/a | -5250.4 | signing_to_pi | n/a | n/a | 4 |
| KXEOWEEK-26MAR14 | 2026-03-17 15:15Z | 0.990 | -5510.3 | signing_to_pi | n/a | n/a | 0 |
| KXEOWEEK-26MAR21 | 2026-03-18 15:15Z | 0.990 | -2857.3 | signing_to_pi | n/a | n/a | 0 |
| KXEOWEEK-26MAR21-1 | 2026-03-24 15:15Z | n/a | -5827.0 | signing_to_pi | n/a | n/a | 1 |
| KXEOWEEK-26MAR28-0 | 2026-03-26 15:15Z | 0.990 | -3441.3 | signing_to_pi | n/a | n/a | 0 |
| KXEOWEEK-26MAR28-1 | 2026-03-30 15:15Z | 0.990 | -5250.0 | signing_to_pi | n/a | n/a | 0 |
| KXEOWEEK-26MAY02-0 | 2026-05-04 15:15Z | 0.990 | -6464.9 | before_signing | n/a | n/a | 0 |
| KXEOWEEK-26MAY02-2 | 2026-05-06 15:15Z | 0.990 | -7067.2 | signing_to_pi | n/a | n/a | 9 |
| KXEOWEEK-26MAY23-0 | 2026-05-21 15:15Z | n/a | -2573.8 | signing_to_pi | n/a | n/a | 5 |
| KXEOWEEK-26MAY23-1 | 2026-05-21 15:15Z | 0.990 | -2489.3 | signing_to_pi | n/a | n/a | 5 |
| KXEOWEEK-26MAY30-0 | 2026-06-02 15:15Z | 0.990 | -5370.4 | signing_to_pi | n/a | n/a | 0 |
| KXEOWEEK-26MAY30-1 | 2026-06-02 15:15Z | 0.990 | -5351.9 | signing_to_pi | n/a | n/a | 0 |
| KXEOWEEK-26OCT03-0 | 2026-10-01 15:15Z | n/a | -3733.9 | before_signing | 1.000 | 0.0000 | 0 |
| KXEOWEEK-26OCT03-1 | 2026-10-01 15:15Z | n/a | -2784.9 | signing_to_pi | 1.000 | 0.0000 | 0 |
| KXEOWEEK-26OCT03-2 | 2026-10-01 15:15Z | n/a | -2511.2 | signing_to_pi | 1.000 | 0.0000 | 0 |
| KXEOWEEK-26OCT10-0 | 2026-10-08 15:15Z | n/a | -3896.6 | signing_to_pi | n/a | n/a | 5 |
| KXEOWEEK-26OCT17-0 | 2026-10-20 15:15Z | 0.990 | -5200.5 | signing_to_pi | 0.990 | 0.0093 | 0 |
| KXEOWEEK-26OCT24-0 | 2026-10-21 15:15Z | n/a | -2849.5 | signing_to_pi | 1.000 | 0.0000 | 0 |
| KXEOWEEK-26OCT24-1 | 2026-10-27 15:15Z | 0.990 | -6895.9 | signing_to_pi | 1.000 | 0.0000 | 0 |
| KXEOWEEK-26SEP05-0 | 2026-09-09 15:15Z | n/a | -7797.9 | signing_to_pi | 1.000 | 0.0000 | 1 |
| KXEOWEEK-26SEP05-1 | 2026-09-09 15:15Z | n/a | -6959.4 | signing_to_pi | 1.000 | 0.0000 | 1 |
| KXEOWEEK-26SEP12-0 | 2026-09-10 15:15Z | 0.990 | -2662.2 | signing_to_pi | 1.000 | 0.0000 | 10 |
| KXEOWEEK-26SEP12-1 | 2026-09-10 15:15Z | 0.990 | -2655.0 | signing_to_pi | 1.000 | 0.0000 | 10 |
| KXEOWEEK-26SEP19-0 | 2026-09-18 15:15Z | n/a | -2571.0 | signing_to_pi | 1.000 | 0.0000 | 1 |
| KXEOWEEK-26SEP19-1 | 2026-09-21 15:15Z | 0.990 | -5482.9 | signing_to_pi | 1.000 | 0.0000 | 0 |
| KXEOWEEK-26SEP19-2 | 2026-09-21 15:15Z | n/a | -5383.1 | signing_to_pi | 1.000 | 0.0000 | 0 |

## IPO family (one cluster, descriptive): reaction to EDGAR filings

Anthropic, PBC (CIK 2130357, ticker ['ANT']) **has already filed publicly on EDGAR**: 14 filings since 2026-06-01 (DRS drafts, then the public S-1 on 2026-10-26, S-1/A amendments, FWPs). The settling documents for the IPO markets (SEC effectiveness, 424B pricing) are therefore pending, not absent. Markets: 12 Kalshi (KXIPOANTHROPIC, trades) and 8 Polymarket (CLOB, 10-minute prices). This is ONE correlated cluster and the filings are leading, not settling, documents, so the table is descriptive and outside the verdict. Entries are the median change in YES price from the price at filing acceptance.

| form | accepted | markets priced | -1 h | +1 min | +15 min | +1 h | +6 h | +24 h |
|---|---|---|---|---|---|---|---|---|
| S-1 | 2026-10-26 13:00Z | 14 | -0.008 / 0.029 (n=12) | +0.000 / 0.001 (n=8) | +0.000 / 0.007 (n=14) | +0.006 / 0.019 (n=14) | +0.000 / 0.015 (n=14) | -0.007 / 0.015 (n=12) |
| S-1/A | 2026-11-02 14:24Z | 11 | +0.000 / 0.005 (n=11) | n/a | +0.000 / 0.000 (n=9) | +0.000 / 0.009 (n=10) | +0.000 / 0.012 (n=11) | +0.000 / 0.009 (n=11) |
| S-1/A | 2026-11-10 11:29Z | 13 | +0.000 / 0.002 (n=13) | +0.000 / 0.000 (n=8) | +0.000 / 0.008 (n=11) | +0.000 / 0.023 (n=11) | +0.005 / 0.029 (n=13) | -0.001 / 0.013 (n=12) |
| FWP | 2026-11-11 01:35Z | 14 | -0.001 / 0.025 (n=14) | -0.005 / 0.005 (n=2) | +0.000 / 0.027 (n=12) | -0.001 / 0.012 (n=14) | -0.001 / 0.016 (n=14) | -0.001 / 0.015 (n=14) |
| FWP | 2026-11-11 01:40Z | 14 | +0.000 / 0.024 (n=14) | -0.006 / 0.006 (n=9) | +0.000 / 0.023 (n=13) | -0.001 / 0.012 (n=13) | +0.000 / 0.015 (n=14) | +0.000 / 0.015 (n=14) |
| FWP | 2026-11-11 01:43Z | 13 | +0.000 / 0.023 (n=13) | n/a | +0.000 / 0.026 (n=12) | +0.000 / 0.010 (n=12) | +0.000 / 0.016 (n=13) | +0.001 / 0.017 (n=13) |
| FWP | 2026-11-12 11:06Z | 11 | +0.001 / 0.003 (n=11) | n/a | +0.000 / 0.001 (n=9) | +0.000 / 0.001 (n=10) | -0.001 / 0.002 (n=11) | +0.000 / 0.014 (n=11) |
| FWP | 2026-11-12 11:08Z | 11 | +0.001 / 0.003 (n=11) | n/a | +0.000 / 0.001 (n=10) | +0.000 / 0.001 (n=10) | -0.001 / 0.002 (n=11) | +0.000 / 0.014 (n=11) |

## Other families

| family | venue | watched markets | open | past_end | settled |
|---|---|---|---|---|---|
| Federal Register | kalshi | 12 | 12 | 0 | 0 |
| Federal Register | polymarket | 1 | 1 | 0 | 0 |
| SEC / EDGAR | kalshi | 16 | 16 | 0 | 0 |
| SEC / EDGAR | polymarket | 35 | 35 | 0 | 0 |
| Strategy fixture | polymarket | 1 | 0 | 0 | 1 |
| court / agency | kalshi | 28 | 28 | 0 | 0 |
| court / agency | polymarket | 2 | 2 | 0 | 0 |
| other | kalshi | 45 | 15 | 0 | 30 |

No allow-listed SEC, Federal Register (non-weekly) or court market has resolved yet, so none has a measurable settling-document timestamp: **0 resolved cases** (INSUFFICIENT DATA for those families). The IPO family's settling documents are pending (see the IPO section). Court markets: no resolved case, and no docket-timestamp source is built yet (CourtListener is the first post-MVP milestone).

## Strategy case (price-based, outside the pooled verdict)

Case: Polymarket 'MicroStrategy sells any Bitcoin by May 31, 2026?' (resolved **No**). t_doc = EDGAR acceptance of 8-K 0001193125-26-249768, 2026-06-01 12:00:16Z (08:00:16 ET), about 8 h after the 23:59 ET May 31 deadline. The filing reports 32 BTC sold May 26-31. Price source: CLOB prices-history (2880 points; one price per point, **no bid/ask**), so everything here is **price-based** and is excluded from the pooled verdict.

| moment | time | YES price |
|---|---|---|
| -5 min | 2026-06-01 11:55Z | 0.101 |
| -3 min | 2026-06-01 11:57Z | 0.161 |
| -1 min | 2026-06-01 11:59Z | 0.250 |
| t_doc | 2026-06-01 12:00Z | 0.354 |
| +1 min | 2026-06-01 12:01Z | 0.418 |
| +2 min (buy) | 2026-06-01 12:02Z | 0.504 |
| +15 min | 2026-06-01 12:15Z | 0.815 |
| +1 h | 2026-06-01 13:00Z | 0.637 |
| +6 h | 2026-06-01 18:00Z | 0.001 |

Peak after t_doc: 0.843 at 2026-06-01 12:18Z; first price >= 0.90 after t_doc: n/a (never reached if n/a). Naive rule 'buy YES at t_doc + 2 min' at 0.504: the market resolved No (the filing satisfied the content of the rule but not the deadline basis), so 100 contracts lose about $51.45 including the Polymarket taker fee (rate 0.04, formula C x rate x p x (1-p) = $1.00). **The document implied Yes; the market resolved No: this is the case evidence_gap must suppress** (deadline_applies_to ambiguous). Note the price was already rising BEFORE the filing was accepted (see the -5/-3/-1 min rows): the market reacted to Strategy's own announcement channel a few minutes ahead of EDGAR, so even for an EDGAR-settled market the filing itself was not the first public signal.

## Interpretation and what to build next (hand-written, post-hoc)

The verdict above is computed from the pre-registered rules. This section is my reading of it, written after seeing the numbers.

**1. Weekly executive orders: no speed edge from being first on the Federal Register.** In 22 of 24 usable weeks (92%) the price was already at 0.90 or above (sustained) days before the public-inspection posting; the median lead is about 2.9 days. The move happens around the signing day (83% of weeks; another 8% before it), when the White House publishes the order, not at public inspection (8%) and not at official publication (0%). A week is usable when a Yes-implied market traded within 24 hours before the posting (the pre-registered wording); 5 further weeks had no such trade and are not counted. Public inspection trails signing by roughly 3-6 days (docs/fedreg-timing.md), so a Federal Register watcher is structurally behind a market that already knows.

**2. The exceptions are real but early and small.** The only two weeks where public inspection was the first public signal are the market's first two (Oct and Nov 2025). In the first, the price sat at 0.82 until 38 seconds after the 11:15 ET posting, then swept to 0.98 within two seconds, so another participant reacted in under a minute; in the second the price drifted from about 0.89 to 0.97 over a few hours. The other 22 usable weeks (Dec 2025 to Oct 2026) show no such case. Two of 24 weeks is 8% (Wilson 95% roughly 2% to 27%); that is too few to call a pattern, and the best window was seconds long.

**3. The P&L numbers need care.** The primary after-fee P&L (buy at the ask 2 minutes after the posting) rests on only 4 of 24 weeks, because thin markets rarely have a quote within 24 hours; it is about zero. The price-based sensitivity (buy at the last trade, ignoring the spread) shows about +$0.018 per contract, but that is carry from buying a near-certain Yes at 0.97-0.99 and holding for days, not information speed: it exists regardless of who is first and ties up capital for days. Kalshi's fee formula is an unverified assumption; the fee-free row bounds it.

**4. Strategy (one case, price-based).** The price began rising about five minutes before the 8-K was accepted (0.10 to 0.25 by 11:59Z) and was at 0.50 two minutes after, then the market resolved No. For this EDGAR-settled market the filing was not the first public signal either (the company's own announcement channel came first), and the deadline-basis ambiguity, not speed, decided the outcome. A naive buy at t+2 min lost about $51 per 100 contracts.

**5. IPO cluster: leading filings are already priced; the settling ones are pending.** Anthropic, PBC filed its S-1 publicly on 2026-10-26 and amended it (Nov 2, Nov 10) with FWPs on Nov 11-12. Across 11-14 markets the median price change after each filing is 0.000 and the mean absolute change is about 0.01-0.03, so these filings did not move the markets. The documents that settle those markets (SEC effectiveness, 424B pricing) have not appeared yet. This is one correlated cluster and a descriptive result.

**6. Other families have no resolved cases** (SEC/other EDGAR, non-weekly Federal Register, court): INSUFFICIENT DATA, not evidence either way.

**What this implies for what to build next**
- **Do not build a speed-driven evidence_gap on the Federal Register path.** The data says the market is days ahead there. evidence_gap stays disabled by design (precision gate, `yes_label == 'Yes'`, ambiguous-deadline suppression).
- **Shift weight to the ambiguity / deadline-risk / resolution-verification tool.** The one hard case in hand (Strategy) is an interpretation case, and the weekly-EO validation (120 of 120 results reproduced from Federal Register data with the venue's own rule) shows the verification side works. Keep the Federal Register watcher lean (authoritative counts, deadline checks), not tuned for latency.
- **Run the one live EDGAR test that exists now:** the Anthropic IPO effectiveness notice and 424B pricing are imminent and have liquid markets. Building S3/S4 (entity linker, SEC watcher with acceptance timestamps) and measuring the reaction to those two documents is the cheapest real test of an EDGAR-first edge, and it will not wait for the weekend schedule.
- A faster channel than the Federal Register exists for executive orders (the White House release at signing). Whether that channel is observable before the price moves is a separate question (E2) and would be a different product from this one; it is not assumed here.


## E2 pre-registration (live test on the Anthropic IPO filings)

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


## Limitations

- Weekly-EO markets only; other families have no resolved cases (see above).
- t_pub = 06:00 ET on the publication date is an assumption; PI times come from the FR API (or the URL timestamp fallback).
- Trades give exact times and sizes; bid/ask come from hourly candles carried forward, so the buy price at t+2 min can be up to 24 h stale (pre-registered limit). Thin markets: absolute numbers are small.
- Kalshi fee formula unverified (assumption stated above); results are also shown fee-free.
- The deciding-document logic assumes the venue resolves strictly by FR signing date, which the validation row above tests market by market.

