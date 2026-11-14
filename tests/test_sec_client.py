from __future__ import annotations

import httpx
import pytest

from prooflag.sec_client import SecAccessError, SecClient, SecHTTPError

UA = "Prooflag someone@example.org"


def client(handler, **kw):  # type: ignore[no-untyped-def]
    sleeps: list[float] = []
    now = [0.0]

    def sleep(s: float) -> None:
        sleeps.append(s)
        now[0] += s

    c = SecClient(
        user_agent=UA,
        max_rps=kw.pop("max_rps", 100.0),
        transport=httpx.MockTransport(handler),
        sleep=sleep,
        clock=lambda: now[0],
        **kw,
    )
    return c, sleeps


def test_sends_the_declared_user_agent_and_accepts_gzip() -> None:
    seen: list[httpx.Request] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"ok": 1})

    c, _ = client(h)
    assert c.get_json("https://data.sec.gov/x") == {"ok": 1}
    assert seen[0].headers["user-agent"] == UA
    assert "gzip" in seen[0].headers["accept-encoding"]
    assert c.stats.requests == 1


def test_403_raises_an_actionable_access_error_and_is_not_retried() -> None:
    calls = []

    def h(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(403)

    c, _ = client(h)
    with pytest.raises(SecAccessError, match="contact"):
        c.get("https://www.sec.gov/files/company_tickers.json")
    assert len(calls) == 1 and c.stats.errors == 1


def test_429_honors_retry_after_then_succeeds() -> None:
    n = {"i": 0}

    def h(req: httpx.Request) -> httpx.Response:
        n["i"] += 1
        return (
            httpx.Response(429, headers={"Retry-After": "7"})
            if n["i"] == 1
            else httpx.Response(200, text="ok")
        )

    c, sleeps = client(h)
    assert c.get_text("https://www.sec.gov/a") == "ok"
    assert 7.0 in sleeps


def test_5xx_is_retried_then_raises_with_the_status() -> None:
    c, _ = client(lambda r: httpx.Response(503), max_retries=2)
    with pytest.raises(SecHTTPError) as ei:
        c.get("https://www.sec.gov/a")
    assert ei.value.status == 503 and c.stats.requests == 3


def test_404_is_raised_immediately() -> None:
    calls = []

    def h(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404)

    c, _ = client(h)
    with pytest.raises(SecHTTPError) as ei:
        c.get("https://www.sec.gov/a")
    assert ei.value.status == 404 and len(calls) == 1


def test_304_is_returned_when_allowed_and_conditional_headers_pass_through() -> None:
    seen: list[httpx.Request] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(304)

    c, _ = client(h)
    r = c.get(
        "https://www.sec.gov/a",
        headers={"If-Modified-Since": "Fri, 13 Nov 2026 21:56:59 GMT"},
        allow_304=True,
    )
    assert r.status == 304
    assert seen[0].headers["if-modified-since"] == "Fri, 13 Nov 2026 21:56:59 GMT"
    c2, _ = client(h)
    with pytest.raises(SecHTTPError):
        c2.get("https://www.sec.gov/a")  # 304 only acceptable when asked for


def test_global_rate_limit_spaces_requests() -> None:
    c, sleeps = client(lambda r: httpx.Response(200, text="x"), max_rps=2.0)
    for _ in range(6):
        c.get_text("https://www.sec.gov/a")
    assert sum(sleeps) == pytest.approx(5 * 0.5)  # 2 requests/second
