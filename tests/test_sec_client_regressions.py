from __future__ import annotations

import httpx
import pytest

from prooflag.sec_client import SecHTTPError
from test_sec_client import client


def test_retry_after_is_capped_so_one_header_cannot_block_for_days() -> None:
    c, sleeps = client(
        lambda r: httpx.Response(503, headers={"Retry-After": "86400"}), max_retries=2
    )
    with pytest.raises(SecHTTPError):
        c.get("https://www.sec.gov/a")
    assert sleeps and max(sleeps) <= 60.0


def test_non_numeric_retry_after_falls_back_to_exponential_backoff() -> None:
    hdr = {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}
    c, sleeps = client(lambda r: httpx.Response(429, headers=hdr), max_retries=1)
    with pytest.raises(SecHTTPError):
        c.get("https://www.sec.gov/a")
    assert sleeps == [0.5]
