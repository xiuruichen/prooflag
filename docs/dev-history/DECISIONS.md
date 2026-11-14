# DECISIONS (autonomous run, no human available)

Every judgment call made without asking, with the reason and how to reverse it. `NEEDS REVIEW` marks anything that
required a decision I could not make safely.

| # | Time | Decision | Reasoning | How to reverse |
|---|---|---|---|---|
| 1 | 23:45 | Start `scripts/run_sec_watcher.py` as a background process for the run | E2 needs detection-lag logs if Anthropic's EFFECT / 424B appears overnight; it polls about 7 requests per 30 s (well under 2 req/s) with the declared User-Agent | Stop the process (Ctrl+C / kill); the DB rows it wrote are append-only history and harmless |
| 2 | 00:05 | E2 median lag counts a market that never sustains 0.90 as infinite lag | Reading of the pre-registered 'median time to first sustained 0.90 >= 5 min'; checker agreed it is defensible | Change `lag_minutes` handling in `edge/e2.py` before any event |
| 3 | 00:05 | E2 runner waits 24 h after an event before writing results | Capacity window is t_doc+24 h; earlier results would be on cut-off data | Lower `SETTLE_WAIT` in `scripts/e2_run.py` |
| 4 | 00:05 | Polymarket trade history from data API v2, CLOB fallback (flagged, excluded from verdict counts if snapshot) | v1 retired; Amendment 1 | n/a |

