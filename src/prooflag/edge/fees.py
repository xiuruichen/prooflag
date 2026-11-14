"""Venue fee formulas for the edge study.

Polymarket (docs.polymarket.com/trading/fees): taker fee = C x rate x (p x (1-p))^exponent, rounded
to 5 decimals, minimum 0.00001; makers pay nothing.
Kalshi: the formula could NOT be verified from its docs (fee pages rate-limited). ASSUMPTION used
throughout: taker fee = ceil-to-cent(0.07 x multiplier x C x p x (1-p)) per order (the series
reports fee_type 'quadratic', fee_multiplier 1). Every study result also reports a fee-free run.
"""

from __future__ import annotations

import math

KALSHI_COEFFICIENT = 0.07  # ASSUMPTION, see module docstring


def kalshi_taker_fee(
    count: float, price: float, *, coefficient: float = KALSHI_COEFFICIENT, multiplier: float = 1.0
) -> float:
    raw = coefficient * multiplier * count * price * (1.0 - price)
    if raw <= 0:
        return 0.0
    # Round to 9 places first so binary float noise (1.4700000000000002) cannot bump a cent.
    return math.ceil(round(raw * 100, 9)) / 100


def polymarket_taker_fee(count: float, price: float, rate: float, exponent: float = 1.0) -> float:
    raw = count * rate * (price * (1.0 - price)) ** exponent
    if raw <= 0:
        return 0.0
    return float(max(round(raw, 5), 0.00001))


def pnl_buy_yes_hold(count: float, price: float, *, yes: bool, fee: float) -> float:
    """Profit of buying ``count`` YES contracts at ``price`` and holding to settlement."""
    gross = count * (1.0 - price) if yes else -count * price
    return gross - fee
