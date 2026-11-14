"""Venue-neutral market and price records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Status = Literal["open", "past_end", "closed", "settled"]
LIVE_STATUSES: tuple[str, ...] = ("open", "past_end", "closed")


@dataclass
class RawMarket:
    venue: str
    market_id: str
    title: str
    rules_primary: str
    rules_secondary: str = ""
    event_id: str | None = None
    event_title: str | None = None
    series_ticker: str | None = None
    category: str | None = None
    venue_tags: list[str] = field(default_factory=list)
    resolution_source: str = ""
    settlement_sources: list[str] = field(default_factory=list)
    open_time: datetime | None = None
    close_time: datetime | None = None
    status: Status = "open"
    result: str | None = None
    yes_bid: float | None = None
    yes_ask: float | None = None
    last_price: float | None = None
    # Kalshi reports contracts; Polymarket reports USD. Never mix them up.
    vol24_contracts: float | None = None
    vol24_usd_est: float | None = None
    open_interest_contracts: float | None = None  # Kalshi only
    liquidity_usd: float | None = None  # Polymarket only
    token_ids: dict[str, str] = field(default_factory=dict)
    # What "yes" means for bid/ask/last. "Yes" for binary markets; the first outcome otherwise.
    yes_label: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PricePoint:
    ts: datetime
    price: float | None
    yes_bid: float | None = None
    yes_ask: float | None = None
    volume: float | None = None
    open_interest: float | None = None
