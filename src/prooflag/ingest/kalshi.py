"""Kalshi public market data (no auth). Volumes are CONTRACTS; dollars are estimated."""

from __future__ import annotations

import logging
import math
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from prooflag.ingest.http import VenueClient
from prooflag.ingest.models import PricePoint, RawMarket, Status

log = logging.getLogger(__name__)
MAX_CANDLES = 5000
TICKER_BATCH = 100

_STATUS: dict[str, Status] = {
    "initialized": "open",
    "active": "open",
    "inactive": "open",
    "closed": "closed",
    "determined": "closed",
    "finalized": "settled",
    "settled": "settled",
}


def _f(x: Any) -> float | None:
    """Parse a numeric field; anything non-numeric, NaN or infinite becomes None."""
    try:
        v = None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None
    return v if v is not None and math.isfinite(v) else None


def _ts(x: Any) -> datetime | None:
    """Tolerant timestamp parse: an unparsable value yields None, never an exception."""
    if not x:
        return None
    try:
        d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    except ValueError:
        log.warning("unparsable timestamp", extra={"value": str(x)[:40]})
        return None
    return d.astimezone(UTC) if d.tzinfo else d.replace(tzinfo=UTC)


def is_multivariate(market: dict[str, Any], event: dict[str, Any] | None = None) -> bool:
    """Combo / multivariate (parlay-style) markets are out of scope."""
    series = (event or {}).get("series_ticker") or ""
    return bool(
        market.get("mve_collection_ticker")
        or str(market.get("ticker", "")).startswith("KXMVE")
        or series.startswith("KXMVE")
    )


class KalshiSource:
    venue = "kalshi"

    def __init__(self, client: VenueClient, base_url: str) -> None:
        self._c = client
        self._base = base_url.rstrip("/")
        self.parse_errors = 0  # markets skipped as malformed in the latest iter/fetch call

    def _safe_parse(self, ev: dict[str, Any] | None, m: Any) -> RawMarket | None:
        try:
            return self.parse_market(ev, m)
        except Exception:
            self.parse_errors += 1
            log.warning("skipping malformed market", exc_info=True)
            return None

    # -- catalog ---------------------------------------------------------------------------
    def iter_events(
        self, *, status: str, series_ticker: str | None = None
    ) -> Iterator[dict[str, Any]]:
        cursor = ""
        while True:
            params: dict[str, Any] = {"status": status, "limit": 200, "with_nested_markets": "true"}
            if series_ticker:
                params["series_ticker"] = series_ticker
            if cursor:
                params["cursor"] = cursor
            data = self._c.get_json(f"{self._base}/events", params)
            yield from data.get("events") or []
            cursor = data.get("cursor") or ""
            if not cursor:
                return

    def iter_markets(
        self, *, status: str = "open", series_ticker: str | None = None
    ) -> Iterator[RawMarket]:
        """Non-sports, non-multivariate markets. Sports events are skipped at the event level."""
        self.parse_errors = 0
        for ev in self.iter_events(status=status, series_ticker=series_ticker):
            if ev.get("category") == "Sports":
                continue
            for m in ev.get("markets") or []:
                rm = self._safe_parse(ev, m)
                if rm is not None:
                    yield rm

    def parse_market(self, ev: dict[str, Any] | None, m: dict[str, Any]) -> RawMarket | None:
        if is_multivariate(m, ev):
            return None
        ev = ev or {}
        bid, ask, last = (
            _f(m.get("yes_bid_dollars")),
            _f(m.get("yes_ask_dollars")),
            _f(m.get("last_price_dollars")),
        )
        contracts = _f(m.get("volume_24h_fp"))
        ref = (
            last
            if last is not None
            else ((bid + ask) / 2 if bid is not None and ask is not None else None)
        )
        usd = contracts * ref if contracts is not None and ref is not None else None
        result = (m.get("result") or "").lower()
        return RawMarket(
            venue=self.venue,
            market_id=m["ticker"],
            title=m.get("title") or ev.get("title") or "",
            rules_primary=m.get("rules_primary") or "",
            rules_secondary=m.get("rules_secondary") or "",
            event_id=m.get("event_ticker") or ev.get("event_ticker"),
            event_title=ev.get("title"),
            series_ticker=ev.get("series_ticker") or None,
            category=ev.get("category") or None,
            settlement_sources=[
                s.get("name", "") for s in ev.get("settlement_sources") or [] if s.get("name")
            ],
            open_time=_ts(m.get("open_time")),
            close_time=_ts(m.get("close_time")),
            status=_STATUS.get(str(m.get("status")), "open"),
            result=result if result in ("yes", "no") else None,
            yes_bid=bid,
            yes_ask=ask,
            last_price=last,
            vol24_contracts=contracts,
            vol24_usd_est=usd,
            open_interest_contracts=_f(m.get("open_interest_fp")),
            raw=m,
        )

    # -- targeted lookups (snapshots / settlement tracking) ----------------------------------
    def fetch_markets(self, tickers: list[str]) -> list[RawMarket]:
        out: list[RawMarket] = []
        self.parse_errors = 0
        for i in range(0, len(tickers), TICKER_BATCH):
            chunk = tickers[i : i + TICKER_BATCH]
            data = self._c.get_json(f"{self._base}/markets", {"tickers": ",".join(chunk)})
            for m in data.get("markets") or []:
                rm = self._safe_parse(None, m)
                if rm is not None:
                    out.append(rm)
        return out

    # -- history -----------------------------------------------------------------------------
    def history(
        self,
        *,
        market_id: str,
        series_ticker: str | None,
        token_id: str | None,
        start: datetime,
        end: datetime,
    ) -> list[PricePoint]:
        if not series_ticker:
            raise ValueError("Kalshi candlesticks need the series ticker")
        return self.price_history(series_ticker, market_id, start, end, 60)

    def price_history(
        self,
        series_ticker: str,
        ticker: str,
        start: datetime,
        end: datetime,
        period_minutes: int = 60,
    ) -> list[PricePoint]:
        """Candlesticks, chunked so each request stays under the 5000-candle cap. A candle with
        no trades has no trade price: price is None (never invented); bid/ask close are kept."""
        step = timedelta(minutes=period_minutes * MAX_CANDLES)
        points: dict[datetime, PricePoint] = {}
        cur = start
        while cur < end:
            nxt = min(cur + step, end)
            data = self._c.get_json(
                f"{self._base}/series/{series_ticker}/markets/{ticker}/candlesticks",
                {
                    "start_ts": int(cur.timestamp()),
                    "end_ts": int(nxt.timestamp()),
                    "period_interval": period_minutes,
                },
            )
            for c in data.get("candlesticks") or []:
                ts = datetime.fromtimestamp(int(c["end_period_ts"]), UTC)
                points[ts] = PricePoint(
                    ts=ts,
                    price=_f((c.get("price") or {}).get("close_dollars")),
                    yes_bid=_f((c.get("yes_bid") or {}).get("close_dollars")),
                    yes_ask=_f((c.get("yes_ask") or {}).get("close_dollars")),
                    volume=_f(c.get("volume_fp")),
                    open_interest=_f(c.get("open_interest_fp")),
                )
            cur = nxt
        return [points[k] for k in sorted(points)]
