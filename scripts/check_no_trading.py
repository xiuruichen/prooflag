"""Fail if order-placement code appears in src/ (Prooflag never trades)."""

import pathlib
import re
import sys

PAT = re.compile(r"(create_order|place_order|submit_order|/portfolio/orders|/order\b)", re.I)
bad = [
    f"{p}:{i}: {line.strip()}"
    for p in pathlib.Path("src").rglob("*.py")
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
    if PAT.search(line)
]
if bad:
    print("trading-related strings found:\n" + "\n".join(bad))
    sys.exit(1)
