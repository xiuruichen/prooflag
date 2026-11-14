"""Minimal global rate limiter (even spacing) with injectable clock/sleep for tests."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        rate_per_sec: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be positive")
        self._interval = 1.0 / rate_per_sec
        self._clock = clock
        self._sleep = sleep
        self._next_ok = 0.0
        self._lock = threading.Lock()
        self.calls = 0
        self.total_wait = 0.0

    def acquire(self) -> None:
        """Block until a request may be sent. Requests are spaced >= 1/rate apart."""
        with self._lock:
            now = self._clock()
            wait = max(0.0, self._next_ok - now)
            self._next_ok = max(now, self._next_ok) + self._interval
            self.calls += 1
            self.total_wait += wait
        if wait > 0:
            self._sleep(wait)
