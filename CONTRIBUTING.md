# Contributing

Prooflag is a research archive and is not actively developed. Bug reports and small fixes are welcome.

Ground rules:

- No trading or order-placement code, and no paid services. `scripts/check_no_trading.py` enforces the first in CI.
- Tests use recorded fixtures only. The test suite blocks network access.
- Before opening a PR, run all of these and make sure they pass:

```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run python scripts/check_no_trading.py
uv run pytest
```

- Add a failing test first for any bug fix.
- Never commit `.env`, anything under `data/`, or a real contact address. A test fails if the contact address appears in a tracked file.
- Do not edit `studies/e2/preregistration.md` except by appending a dated amendment before the event it covers.
- Respect SEC fair access: declared User-Agent and at most 2 requests per second.
