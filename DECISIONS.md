# DECISIONS (autonomous run, no human available)

Every judgment call made without asking, with the reason and how to reverse it. `NEEDS RAY` marks anything that
required a decision I could not make safely.

| # | Time | Decision | Reasoning | How to reverse |
|---|---|---|---|---|
| 1 | 23:45 | Start `scripts/run_sec_watcher.py` as a background process for the run | E2 needs detection-lag logs if Anthropic's EFFECT / 424B appears overnight; it polls about 7 requests per 30 s (well under 2 req/s) with the declared User-Agent | Stop the process (Ctrl+C / kill); the DB rows it wrote are append-only history and harmless |
