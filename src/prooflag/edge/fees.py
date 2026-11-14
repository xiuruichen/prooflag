"""Venue fee formulas for the edge study.

Kalshi (standard schedule confirmed by the author, 2026-11-14): taker fee = round_up_to_cent(0.07 x
multiplier x C x p x (1-p)); maker fee on maker-fee markets = round_up_to_cent(0.0175 x multiplier x
C x p x (1-p)); rounding is up to the cent PER ORDER. Each series has a fee type from the API:
'quadratic' (takers only), 'quadratic_with_maker_fees' (takers and makers), 'fee_free'; 'flat' and
any other type are NOT guessed and raise UnsupportedFeeTypeError.
Polymarket (docs.polymarket.com/trading/fees): taker fee = C x rate x (p x (1-p))^exponent, rounded
to 5 decimals, minimum 0.00001; makers pay nothing.
"""

from __future__ import annotations

import math

KALSHI_COEFFICIENT = 0.07
KALSHI_MAKER_COEFFICIENT = 0.0175


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


class UnsupportedFeeTypeError(Exception):
    """A series fee type whose formula we do not know; never guessed."""


def kalshi_fee(
    fee_type: str, multiplier: float, count: float, price: float, *, role: str = "taker"
) -> float:
    """Kalshi fee for one order, by the series' fee type (see module docstring)."""
    if role not in ("taker", "maker"):
        raise ValueError(f"role must be 'taker' or 'maker', got {role!r}")
    if fee_type == "fee_free":
        return 0.0
    if fee_type not in ("quadratic", "quadratic_with_maker_fees"):
        raise UnsupportedFeeTypeError(f"unsupported Kalshi fee type {fee_type!r}")
    if role == "taker":
        return kalshi_taker_fee(count, price, multiplier=multiplier)
    if fee_type == "quadratic":
        return 0.0
    return kalshi_taker_fee(
        count, price, coefficient=KALSHI_MAKER_COEFFICIENT, multiplier=multiplier
    )
