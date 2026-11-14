"""HTTP client for public venue APIs: rate limited, retrying, generic User-Agent."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from prooflag.ratelimit import RateLimiter

log = logging.getLogger(__name__)


class VenueHTTPError(Exception):
    def __init__(self, status: int, url: str, body: str) -> None:
        super().__init__(f"HTTP {status} for {url}: {body[:200]}")
        self.status = status
        self.url = url
        self.body = body


class VenueClient:
    def __init__(
        self,
        *,
        user_agent: str,
        max_rps: float,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        max_retries: int = 4,
        timeout: float = 60.0,
    ) -> None:
        self._http = httpx.Client(
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            transport=transport,
            timeout=timeout,
        )
        self._limiter = RateLimiter(max_rps, clock=clock, sleep=sleep)
        self._sleep = sleep
        self._max_retries = max_retries

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        last: Exception | None = None
        for attempt in range(self._max_retries + 1):
            self._limiter.acquire()
            try:
                resp = self._http.get(url, params=params)
            except httpx.TransportError as e:
                last = e
                log.warning("transport error", extra={"url": url, "attempt": attempt})
            else:
                if resp.status_code == 429 or resp.status_code >= 500:
                    last = VenueHTTPError(resp.status_code, url, resp.text)
                    log.warning("retryable status", extra={"url": url, "status": resp.status_code})
                elif resp.status_code >= 400:
                    raise VenueHTTPError(resp.status_code, url, resp.text)
                else:
                    return resp.json()
            if attempt < self._max_retries:
                self._sleep(0.5 * (2**attempt))
        assert last is not None
        raise last

    def close(self) -> None:
        self._http.close()
