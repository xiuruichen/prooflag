"""Global test guards: no live network (loopback allowed for local app tests)."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any

import pytest

_real_connect = socket.socket.connect


def _is_loopback(address: Any) -> bool:
    if not isinstance(address, tuple) or not address:
        return True  # AF_UNIX / non-IP sockets
    host = address[0]
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def _block_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def guarded_connect(self: socket.socket, address: Any) -> Any:
        if not _is_loopback(address):
            raise RuntimeError(f"network access blocked in tests: {address!r}")
        return _real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)

    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host not in ("localhost", "127.0.0.1", "::1", None):
            raise RuntimeError(f"DNS lookup blocked in tests: {host!r}")
        return _orig_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


_orig_getaddrinfo = socket.getaddrinfo
