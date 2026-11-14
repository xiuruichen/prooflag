import socket

import pytest


def test_guard_blocks_external_connect() -> None:
    with pytest.raises(RuntimeError, match="blocked"):
        socket.create_connection(("93.184.216.34", 80), timeout=1)


def test_guard_blocks_external_dns() -> None:
    with pytest.raises(RuntimeError, match="blocked"):
        socket.getaddrinfo("example.com", 80)


def test_guard_allows_loopback() -> None:
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    c = socket.create_connection(srv.getsockname(), timeout=2)
    c.close()
    srv.close()
