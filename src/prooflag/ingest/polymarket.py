"""Polymarket public data: Gamma (catalog, keyset cursors only) and CLOB (price history)."""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from prooflag.ingest.http import VenueClient
from prooflag.ingest.models import PricePoint, RawMarket, Status

log = logging.getLogger(__name__)
EVENTS_PAGE_LIMIT = 50  # >50 is served gzip-only (HTTP 406 otherwise)
CONDITION_BATCH = 40  # ~100 ids already trips a 414 (URI too long)
HISTORY_CHUNK = timedelta(days=14)  # 20-day ranges are rejected with HTTP 400


def _f(x: Any) -> float | None:
    """Parse a numeric field; anything non-numeric, NaN or infinite becomes None."""
    try:
        v = None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None
    return v if v is not None and math.isfinite(v) else None


def _jlist(x: Any) -> list[Any]:
    """Gamma returns some arrays as JSON-encoded strings (outcomePrices, clobTokenIds, ...)."""
    if isinstance(x, list):
        return x
    if isinstance(x, str) and x:
        try:
            v = json.loads(x)
        except json.JSONDecodeError:
            return []
        return v if isinstance(v, list) else []
    return []


def _dt(x: Any) -> datetime | None:
    if not x:
        return None
    s = str(x).replace("Z", "+00:00")
    if len(s) == 10:
        s += "T00:00:00+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        log.warning("unparsable timestamp", extra={"value": s[:40]})
        return None
    return d.astimezone(UTC) if d.tzinfo else d.replace(tzinfo=UTC)


def _is_sports(ev: dict[str, Any]) -> bool:
    return any((t.get("label") or "").lower() == "sports" for t in ev.get("tags") or [])


class PolymarketSource:
    venue = "polymarket"

    def __init__(
        self,
        client: VenueClient,
        gamma_base: str,
        clob_base: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._c = client
        self._gamma = gamma_base.rstrip("/")
        self._clob = clob_base.rstrip("/")
        self._clock = clock
        self.parse_errors = 0  # markets skipped (malformed or without an id) in the latest call

    def _safe_parse(self, ev: dict[str, Any] | None, m: Any) -> RawMarket | None:
        try:
            return self.parse_market(ev, m)
        except Exception:
            self.parse_errors += 1
            log.warning("skipping malformed market", exc_info=True)
            return None

    # -- catalog ---------------------------------------------------------------------------
    def iter_markets(self) -> Iterator[RawMarket]:
        """Open (incl. past-end, unresolved) markets. Keyset cursors only: offset is rejected."""
        cursor = ""
        self.parse_errors = 0
        while True:
            params: dict[str, Any] = {
                "closed": "false",
                "active": "true",
                "archived": "false",
                "limit": EVENTS_PAGE_LIMIT,
            }
            if cursor:
                params["after_cursor"] = cursor
            data = self._c.get_json(f"{self._gamma}/events/keyset", params)
            for ev in data.get("events") or []:
                for m in ev.get("markets") or []:
                    rm = self._safe_parse(ev, m)
                    if rm is not None:
                        yield rm
            cursor = data.get("next_cursor") or ""
            if not cursor:
                return

    def parse_market(self, ev: dict[str, Any] | None, m: dict[str, Any]) -> RawMarket | None:
        ev = ev or {}
        if _is_sports(ev) or m.get("comboStatus") == "enabled":
            return None
        if not m.get("conditionId"):
            # Live finding: some markets have an empty conditionId; keying on '' would merge
            # unrelated markets into one row. They cannot be identified, so they are skipped.
            raise ValueError("market has no conditionId")
        outcomes = [str(o) for o in _jlist(m.get("outcomes"))]
        prices = [_f(p) for p in _jlist(m.get("outcomePrices"))]
        tokens = [str(t) for t in _jlist(m.get("clobTokenIds"))]
        names = [o.lower() for o in outcomes]
        yes_i = names.index("yes") if "yes" in names else 0
        end = _dt(m.get("endDate"))
        status: Status
        result: str | None = None
        if m.get("closed"):
            status = "settled"
            known = [(p, i) for i, p in enumerate(prices) if p is not None]
            if known:
                top, win = max(known)
                winner = names[win] if win < len(names) else None
                result = winner if top >= 0.99 else "other"
        elif end is not None and end < self._clock():
            status = "past_end"  # awaiting resolution: exactly the window Prooflag watches
        else:
            status = "open"
        token_ids = {names[i]: tokens[i] for i in range(min(len(names), len(tokens)))}
        if "yes" not in token_ids and tokens:
            # Non-Yes/No market: bid/ask/last and history refer to the first outcome; alias it.
            token_ids["yes"] = tokens[yes_i] if yes_i < len(tokens) else tokens[0]
        vol = _f(m.get("volume24hr"))
        return RawMarket(
            venue=self.venue,
            market_id=m["conditionId"],
            title=m.get("question") or "",
            rules_primary=m.get("description") or "",
            event_id=str(ev["id"]) if ev.get("id") is not None else None,
            event_title=ev.get("title"),
            venue_tags=[t.get("label") for t in ev.get("tags") or [] if t.get("label")],
            resolution_source=m.get("resolutionSource") or "",
            open_time=_dt(m.get("startDate")),
            close_time=end,
            status=status,
            result=result,
            yes_bid=_f(m.get("bestBid")),
            yes_ask=_f(m.get("bestAsk")),
            last_price=_f(m.get("lastTradePrice")),
            vol24_usd_est=vol,  # Polymarket volume is already USD
            liquidity_usd=_f(
                m.get("liquidityNum") if m.get("liquidityNum") is not None else m.get("liquidity")
            ),
            token_ids=token_ids,
            yes_label=outcomes[yes_i] if yes_i < len(outcomes) else None,
            raw={**m, "_yes_index": yes_i},
        )

    # -- targeted lookups --------------------------------------------------------------------
    def fetch_markets(self, condition_ids: list[str]) -> list[RawMarket]:
        """Look up by condition id. Closed markets are absent unless closed=true is also queried."""
        found: dict[str, RawMarket] = {}
        self.parse_errors = 0
        for closed in (False, True):
            todo = [c for c in condition_ids if c not in found]
            for i in range(0, len(todo), CONDITION_BATCH):
                chunk = todo[i : i + CONDITION_BATCH]
                params: dict[str, Any] = {"condition_ids": chunk, "limit": 100}
                if closed:
                    params["closed"] = "true"
                for m in self._c.get_json(f"{self._gamma}/markets", params) or []:
                    rm = self._safe_parse(None, m)
                    if rm is not None:
                        found[rm.market_id] = rm
        return list(found.values())

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
        if not token_id:
            raise ValueError("Polymarket history needs the YES token id")
        return self.price_history(token_id, start, end, 60)

    def price_history(
        self, token_id: str, start: datetime, end: datetime, fidelity_minutes: int = 60
    ) -> list[PricePoint]:
        points: dict[datetime, PricePoint] = {}
        cur = start
        while cur < end:
            nxt = min(cur + HISTORY_CHUNK, end)
            data = self._c.get_json(
                f"{self._clob}/prices-history",
                {
                    "market": token_id,
                    "startTs": int(cur.timestamp()),
                    "endTs": int(nxt.timestamp()),
                    "fidelity": fidelity_minutes,
                },
            )
            for h in data.get("history") or []:
                ts = datetime.fromtimestamp(int(h["t"]), UTC)
                points[ts] = PricePoint(ts=ts, price=_f(h.get("p")))
            cur = nxt
        return [points[k] for k in sorted(points)]
