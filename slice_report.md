# Slice scan v2 (2026-11-14T02:24:41+00:00)

Kalshi base: `https://external-api.kalshi.com/trade-api/v2`; COMPLETED=True; events=22133 (excluded sports/mve=9078); open markets scanned=82481
Polymarket: COMPLETED=True; events=19403 (excluded sports=11964); open markets scanned=26960; skipped expired-unresolved=7129
Meaningful (regex pass): vol24>=1000 OR Kalshi OI>=2000. Polymarket liquidity / event OI NOT used; stored separately.

| tag | venue | regex-matched | meaningful |
|---|---|---|---|
| court | kalshi | 5471 | 317 |
| court | polymarket | 343 | 24 |
| fed_register | kalshi | 46 | 29 |
| fed_register | polymarket | 24 | 1 |
| press_release | kalshi | 805 | 156 |
| press_release | polymarket | 1264 | 91 |
| sec | kalshi | 354 | 114 |
| sec | polymarket | 372 | 30 |

Total regex-matched: 8642; meaningful: 755
