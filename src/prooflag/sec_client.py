"""HTTP client for sec.gov / data.sec.gov.

Declared User-Agent, <= 2 req/s, retries, conditional GETs.

The User-Agent carries the contact email (SEC fair-access policy), so this client is the ONLY place
the contact is sent, and only to SEC hosts.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from prooflag.ratelimit import RateLimiter

log = logging.getLogger(__name__)


class SecHTTPError(Exception):
    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"SEC HTTP {status} for {url}")
        self.status = status
        self.url = url


class SecAccessError(SecHTTPError):
    """HTTP 403: the SEC refuses automated access, usually a missing/invalid contact in the UA."""

    def __init__(self, url: str) -> None:
        super().__init__(403, url)
        self.args = (
            f"SEC rejected the request (403) for {url}: set PROOFLAG_CONTACT_EMAIL to a real "
            "contact (User-Agent must declare one) and keep to <= 2 requests/second",
        )


@dataclass(frozen=True)
class SecResponse:
    status: int
    body: bytes
    headers: dict[str, str]

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


@dataclass
class SecStats:
    requests: int = 0
    errors: int = 0
    retries: int = 0


class SecClient:
    def __init__(
        self,
        *,
        user_agent: str,
        max_rps: float = 2.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        max_retries: int = 4,
        timeout: float = 60.0,
    ) -> None:
        self._http = httpx.Client(
            headers={"User-Agent": user_agent}, transport=transport, timeout=timeout
        )
        self._limiter = RateLimiter(max_rps, clock=clock, sleep=sleep)
        self._sleep = sleep
        self._max_retries = max_retries
        self.stats = SecStats()

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        allow_304: bool = False,
    ) -> SecResponse:
        last_status = 0
        for attempt in range(self._max_retries + 1):
            self._limiter.acquire()
            self.stats.requests += 1
            try:
                resp = self._http.get(url, headers=headers, params=params)
            except httpx.TransportError:
                last_status = 0
                self.stats.errors += 1
                log.warning("sec transport error", extra={"url": url, "attempt": attempt})
            else:
                code = resp.status_code
                if code == 200 or (code == 304 and allow_304):
                    return SecResponse(code, resp.content, dict(resp.headers))
                if code == 403:
                    self.stats.errors += 1
                    raise SecAccessError(url)
                if code == 429 or code >= 500:
                    last_status = code
                    self.stats.errors += 1
                    retry_after = resp.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after and retry_after.isdigit() else None
                    if attempt < self._max_retries:
                        self.stats.retries += 1
                        self._sleep(wait if wait is not None else 0.5 * (2**attempt))
                    continue
                self.stats.errors += 1
                raise SecHTTPError(code, url)
        raise SecHTTPError(last_status, url)

    def get_json(self, url: str, **kw: Any) -> Any:
        return json.loads(self.get(url, **kw).body)

    def get_text(self, url: str, **kw: Any) -> str:
        return self.get(url, **kw).text

    def close(self) -> None:
        self._http.close()
