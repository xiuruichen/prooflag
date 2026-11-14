"""Statistics and the pre-registered verdict rules (docs/dev-history/PLAN.md E1 + Amendment A)."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field

# Pre-registered thresholds. Do not tune these after seeing results.
MIN_WEEKS = 10
SHARE_PRICE_LED = 0.70  # share of weeks with the price already >= 0.90 at the posting
PNL_UPPER_FLOOR = 0.02  # $ per contract
MIN_LAG_MINUTES = 5.0
MIN_CAPACITY_USD = 10.0  # median per-week after-fee profit available to a taker


def quantile(xs: Sequence[float], q: float) -> float:
    s = sorted(xs)
    if not s:
        raise ValueError("quantile of empty sequence")
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def bootstrap_mean_ci(
    xs: Sequence[float], *, resamples: int = 10_000, seed: int = 1, alpha: float = 0.05
) -> tuple[float, float, float]:
    """Mean with a percentile bootstrap CI (resampling the units, e.g. weeks). Deterministic."""
    if not xs:
        raise ValueError("bootstrap of empty sequence")
    rng = random.Random(seed)
    n = len(xs)
    means = sorted(sum(xs[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    mean = sum(xs) / n
    return mean, quantile(means, alpha / 2), quantile(means, 1 - alpha / 2)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


@dataclass
class Verdict:
    label: str
    reasons: list[str] = field(default_factory=list)


def verdict(
    *,
    n_weeks: int,
    share_ge90_at_pi: float,
    pnl_ci: tuple[float, float, float] | None,
    median_lag_minutes: float,
    median_capacity_usd: float,
) -> Verdict:
    """Apply the pre-registered rules. NO SPEED EDGE takes precedence over EDGE POSSIBLE."""
    if n_weeks < MIN_WEEKS:
        return Verdict("INSUFFICIENT DATA", [f"only {n_weeks} usable weeks (< {MIN_WEEKS})"])
    no_edge: list[str] = []
    if share_ge90_at_pi >= SHARE_PRICE_LED:
        no_edge.append(
            f"price already >= 0.90 at the posting in {share_ge90_at_pi:.0%} of weeks "
            f"(>= {SHARE_PRICE_LED:.0%})"
        )
    if pnl_ci is not None and pnl_ci[2] <= PNL_UPPER_FLOOR:
        no_edge.append(
            f"upper 95% bound of mean after-fee P&L ${pnl_ci[2]:.3f} <= ${PNL_UPPER_FLOOR}"
        )
    lo = pnl_ci[1] if pnl_ci is not None else float("-inf")
    edge_criteria = lo > 0 and median_lag_minutes >= MIN_LAG_MINUTES
    if edge_criteria and median_capacity_usd < MIN_CAPACITY_USD and not no_edge:
        no_edge.append(
            f"edge criteria hold but median capacity ${median_capacity_usd:.2f} < "
            f"${MIN_CAPACITY_USD:.0f}: not tradable at size"
        )
    if no_edge:
        return Verdict("NO SPEED EDGE", no_edge)
    if edge_criteria and median_capacity_usd >= MIN_CAPACITY_USD:
        return Verdict(
            "EDGE POSSIBLE",
            [
                f"lower 95% bound ${lo:.3f} > 0, median lag {median_lag_minutes:.1f} min >= "
                f"{MIN_LAG_MINUTES:.0f}, median capacity ${median_capacity_usd:.2f}"
            ],
        )
    why = (
        "no after-fee P&L estimate (no usable ask)"
        if pnl_ci is None
        else "neither rule is satisfied"
    )
    return Verdict("INSUFFICIENT DATA", [f"inconclusive: {why}"])
