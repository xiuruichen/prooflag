from __future__ import annotations

import httpx
import pytest
from ingest_helpers import UA, body_of, fixture, json_response

from prooflag.config import Settings
from prooflag.ingest.http import VenueClient, VenueHTTPError
from prooflag.ratelimit import RateLimiter


def test_rate_limiter_spaces_requests_evenly() -> None:
    now = [0.0]
    slept: list[float] = []

    def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    rl = RateLimiter(4.0, clock=lambda: now[0], sleep=sleep)
    for _ in range(5):
        rl.acquire()
    assert sum(slept) == pytest.approx(4 * 0.25)
    assert rl.calls == 5


def test_rate_limiter_rejects_non_positive_rate() -> None:
    with pytest.raises(ValueError):
        RateLimiter(0)


def test_retries_5xx_then_succeeds(make_client, requests_log) -> None:  # type: ignore[no-untyped-def]
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 3 else json_response({"ok": True})

    assert make_client(handler).get_json("https://x.test/a") == {"ok": True}
    assert len(requests_log) == 3


def test_4xx_is_not_retried_and_carries_status_and_body(make_client, requests_log) -> None:  # type: ignore[no-untyped-def]
    rec = fixture("poly_offset_422.json")

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(rec["status"], json=rec["body"])

    with pytest.raises(VenueHTTPError) as ei:
        make_client(handler).get_json("https://gamma.test/markets/keyset", {"offset": 10})
    assert ei.value.status == 422
    assert "offset is not allowed" in ei.value.body
    assert len(requests_log) == 1


def test_gzip_required_406_is_surfaced(make_client) -> None:  # type: ignore[no-untyped-def]
    rec = fixture("poly_events_limit100_406.json")
    handler = lambda req: httpx.Response(rec["status"], json=rec["body"])  # noqa: E731
    with pytest.raises(VenueHTTPError) as ei:
        make_client(handler).get_json("https://gamma.test/events/keyset", {"limit": 100})
    assert ei.value.status == 406
    assert "gzip_required" in ei.value.body


def test_gives_up_after_max_retries(make_client, requests_log) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(VenueHTTPError) as ei:
        make_client(lambda r: httpx.Response(429)).get_json("https://x.test/a")
    assert ei.value.status == 429
    assert len(requests_log) == 5  # 1 + 4 retries


def test_venue_requests_never_carry_the_contact_email() -> None:
    s = Settings(contact_email="private.person@example.org", _env_file=None)
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return json_response({})

    c = VenueClient(
        user_agent=s.venue_user_agent,
        max_rps=1000,
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,
    )
    c.get_json("https://x.test/a", {"q": "1"})
    blob = " ".join(f"{k}={v}" for k, v in seen[0].headers.items()) + str(seen[0].url)
    assert "private.person@example.org" not in blob
    assert "@" not in seen[0].headers["user-agent"]
    assert s.user_agent == "Prooflag private.person@example.org"  # SEC-only UA still has it


def test_default_headers_ask_for_gzip(make_client, requests_log) -> None:  # type: ignore[no-untyped-def]
    make_client(lambda r: json_response(body_of("kalshi_events_last_page_empty.json"))).get_json(
        "https://x.test/a"
    )
    assert "gzip" in requests_log[0].headers["accept-encoding"]
    assert requests_log[0].headers["user-agent"] == UA
