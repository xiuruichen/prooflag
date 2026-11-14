# Do prediction markets lag the public documents that settle them?

A pre-registered look at Federal Register executive orders, one SEC 8-K, and the Anthropic IPO filings.

Numbers below come from `docs/edge-study.md`, which `scripts/edge_study.py` regenerates offline from the committed inputs in `studies/e1/inputs/`. Fetch time of the inputs: 2026-11-14 04:03 UTC. Prooflag is a research archive, not a trading tool, and nothing here is financial advice.

## Summary

| Case | Question | Result |
|---|---|---|
| E1: weekly executive-order markets (Kalshi `KXEOWEEK`) | Does the price move at Federal Register public inspection or publication? | **NO SPEED EDGE.** In 22 of 24 usable weeks (92%, Wilson 95% [74%, 98%]) the price was already at 0.90 or above a median of about 2.9 days before the posting. |
| Strategy (MSTR) 8-K, Polymarket "sells any Bitcoin by May 31, 2026?" | Is the filing a tradable signal? | **No.** The price rose about 5 minutes before the 8-K was accepted. A naive buy 2 minutes after lost about $51 per 100 contracts, because the market resolved No on the deadline wording. |
| Anthropic S-1, S-1/A and FWP filings | Do the leading filings move the IPO markets? | **No.** Median price change after each filing was within ±0.007 across 11–14 markets. Descriptive, one correlated cluster. |
| E2: Anthropic EFFECT notice and 424B pricing prospectus | Do the settling filings move the markets? | **Pending.** Pre-registered, events not yet observed (see E2 below). |

## 1. Method

**Documents and times.** SEC acceptance time is `acceptanceDateTime` from `data.sec.gov` submissions (UTC). It matched the filing-index "Accepted" stamp on 15 of 15 filings checked (`docs/edgar-timing.md`). Federal Register public-inspection time is `filed_at` from the API, and 40 of 40 executive orders appeared on public inspection at least 12.8 hours before publication (`docs/fedreg-timing.md`).

**Prices.** Trade-level data (second-resolution timestamps and sizes) from the Kalshi trades endpoints. Bid and ask come from hourly candles carried forward, and a quote older than 24 hours counts as no quote. Polymarket data comes from the CLOB price history, which has no bid or ask.

**Fees.** Kalshi taker fee `round_up_to_cent(0.07 × multiplier × C × p × (1−p))` per order, with the series' fee type read from the API. Polymarket taker fee `C × rate × p × (1−p)` with the market's `feeSchedule`. Fee-free results are reported alongside.

**Independence.** The unit is the week (or the issuer cluster), never the market. The Anthropic and OpenAI IPO markets are one correlated cluster.

**Pre-registered verdict rules** (written before looking at results, `docs/dev-history/PLAN.md` §10d and Amendment A):
- INSUFFICIENT DATA if fewer than 10 usable weeks.
- NO SPEED EDGE if at least 70% of weeks had the price at 0.90 or above at the posting, or the upper 95% bound of mean after-fee P&L is at most $0.02.
- EDGE POSSIBLE only if the lower 95% bound of mean after-fee P&L is above $0, the median lag is at least 5 minutes, and the median per-week capacity (after-fee profit available below 0.95) is at least $10. If those edge criteria hold but capacity is lower, the verdict is NO SPEED EDGE ("not tradable at size").
- Anything else is inconclusive.

The verdict is computed by code (`src/prooflag/edge/stats.py`), not written by hand.

## 2. E1: weekly executive orders

120 resolved weekly markets were reproduced from Federal Register data using each market's own rule (120 of 120 matched the recorded result). 24 independent weeks were usable.

| quantity | value |
|---|---|
| weeks with price ≥ 0.90 at or before public inspection | 22 of 24 (92%) |
| median lag, first sustained 0.90 minus posting | −4,206 minutes (about 2.9 days *before*) |
| after-fee P&L per contract, buy at the ask 2 minutes after posting | mean $0.0023, 95% CI [$0.0000, $0.0070], rests on 4 of 24 weeks |
| median per-week capacity | $0.00 |

Where the move happens: at signing, when the White House publishes the order (83% of weeks, another 8% before it), not at public inspection (8%) and not at official publication (0%). Public inspection trails signing by roughly 3–6 days, so a Federal Register watcher is structurally behind a market that already knows.

The exceptions were the market's first two weeks (October and November 2025). In the first, the price sat at 0.82 until 38 seconds after the posting, then went to 0.98 within two seconds. Two weeks out of 24 is too few to call a pattern.

The price-based sensitivity of +$0.018 per contract (buy at the last trade, ignore the spread) is carry from buying a near-certain Yes at 0.97–0.99 and holding for days. It does not depend on being first.

## 3. Strategy 8-K

Market: Polymarket "MicroStrategy sells any Bitcoin by May 31, 2026?", resolved No after two UMA proposals were disputed. The rule resolves Yes "if MicroStrategy sells any of its Bitcoin by 11:59 PM ET on the date specified in the title". It does not say whether the deadline applies to the sale or to its publication.

The 8-K (accession `0001193125-26-249768`) was accepted 2026-06-01 12:00:16 UTC, about 8 hours after the deadline, and reports 32 BTC sold between May 26 and 31.

| moment | YES price |
|---|---|
| 5 min before acceptance | 0.101 |
| 1 min before | 0.250 |
| acceptance | 0.354 |
| +2 min | 0.504 |
| +15 min | 0.815 |
| +6 h | 0.001 |

The price started rising before the filing was public on EDGAR, so the filing was not the first signal. The content of the filing satisfied the rule and the market still resolved No, because the deadline-basis ambiguity decided it. This one case is price-based (no bid or ask) and sits outside the pooled verdict. It is the reason Prooflag's compiler marks the rule `ambiguous` and why any future evidence-gap signal would have to be suppressed for it.

## 4. Anthropic S-1 filings

Anthropic, PBC filed its S-1 publicly on 2026-10-26, amended it on Nov 2 and Nov 10, and filed FWPs on Nov 11–12. The cluster has 20 markets (12 Kalshi, 8 Polymarket); 11–14 had a price at each filing. The median change in YES price after each filing stayed within ±0.007 at every horizon from 1 minute to 24 hours, and the mean absolute change was about 0.01–0.03. These filings are leading documents, so this is descriptive.

## 5. E2: live test on the settling filings (pending)

The settling documents are the SEC effectiveness notice (`EFFECT`) and the final pricing prospectus (`424B*`). The analysis rules were fixed before either event.

| item | value |
|---|---|
| Pre-registration commit | `efb69aa`, 2026-11-13 23:23 −05:00 (04:23 UTC) |
| Pre-registration text | `studies/e2/preregistration.md` |
| Amendment 1 (pre-event) | commit `e0b03c9` (2026-11-13 23:46 −05:00, 04:46 UTC); EDGAR had no EFFECT or 424B for Anthropic at 04:45 UTC |
| Runner | `scripts/e2_run.py` (waits 24 hours after an event before writing results) |
| Results | `studies/e2/results.md` and `results.json` |

Times written inside the documents (for example "about 04:30 UTC" or "dated 04:52 UTC") are approximate; the commit timestamps are authoritative. The commit hashes and dates refer to the original private repository's history. To check that the pre-registration came before the event, compare those commit dates with the EDGAR acceptance times in the results.

**Result: _pending_.**

| | Event A (EFFECT) | Event B (424B) |
|---|---|---|
| Acceptance time (UTC) | _to be filled by the runner_ | _to be filled by the runner_ |
| Markets counted | _ | _ |
| Share moved within 5 minutes | _ | _ |
| Median lag (minutes) | _ | _ |
| Capacity ($, net of fees) | _ | _ |
| Verdict | _ | _ |

The E2 verdict (DEAD, MIXED, ALIVE provisional, INCONCLUSIVE, or INSUFFICIENT DATA) is whatever `scripts/e2_run.py` writes to `studies/e2/results.md`. Copy it here unchanged.

## 6. Limitations

- Weekly executive orders only; other families (non-weekly Federal Register, SEC, court) have no resolved cases, which is insufficient data and not evidence either way.
- Official publication time (06:00 ET on the publication date) is an assumption.
- Bid and ask come from hourly candles and can be up to 24 hours stale, and the primary P&L rests on 4 of 24 weeks. Thin markets make absolute numbers small.
- Strategy is a single case, price-based.
- The IPO cluster is one correlated unit and was observed after the fact; only E2 is a prospective test.
- Venue data was fetched once and may differ from what the venues serve today.

## 7. Reproducing

```bash
uv sync
uv run python scripts/edge_study.py     # regenerates docs/edge-study.md from studies/e1/inputs/, no network
uv run python scripts/run_ingest_once.py   # fill the local DB first
uv run python scripts/e2_run.py         # E2, needs .env and network
```
