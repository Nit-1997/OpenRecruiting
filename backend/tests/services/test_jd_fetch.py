"""SSRF guard tests for jd_fetch — no network (socket.getaddrinfo is mocked)."""
from __future__ import annotations

import socket

import pytest

from app.services.intake import jd_fetch
from app.services.intake.jd_fetch import (
    SsrfBlockedError,
    _ip_blocked,
    fetch_url_text,
    find_first_url,
    validate_url,
)


def test_find_first_url_in_free_text():
    assert (
        find_first_url("apply here https://co.com/jobs/123, 5 yrs req")
        == "https://co.com/jobs/123"
    )
    assert find_first_url("just some role notes, no link") is None
    assert find_first_url("trailing dot https://x.com/a.") == "https://x.com/a"


def _patch_resolve(monkeypatch, ip: str) -> None:
    def fake_getaddrinfo(host, *args, **kwargs):
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, None, None, "", (ip, 0))]

    monkeypatch.setattr(jd_fetch.socket, "getaddrinfo", fake_getaddrinfo)


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "10.0.0.5", "192.168.1.10", "172.16.0.1", "169.254.169.254", "0.0.0.0", "::1"],
)
def test_blocks_private_loopback_and_metadata(monkeypatch, ip):
    _patch_resolve(monkeypatch, ip)
    with pytest.raises(SsrfBlockedError):
        validate_url("https://evil.example.com/jd")


def test_allows_public_host(monkeypatch):
    _patch_resolve(monkeypatch, "93.184.216.34")
    assert validate_url("https://example.com/jobs/123") == "https://example.com/jobs/123"


def test_rejects_non_https(monkeypatch):
    _patch_resolve(monkeypatch, "93.184.216.34")
    with pytest.raises(SsrfBlockedError):
        validate_url("http://example.com/jd")
    with pytest.raises(SsrfBlockedError):
        validate_url("file:///etc/passwd")


def test_rejects_missing_host():
    with pytest.raises(SsrfBlockedError):
        validate_url("https:///no-host")


def test_ip_blocked_helper():
    assert _ip_blocked("169.254.169.254") is True
    assert _ip_blocked("127.0.0.1") is True
    assert _ip_blocked("::1") is True
    assert _ip_blocked("not-an-ip") is True
    assert _ip_blocked("8.8.8.8") is False


def test_ip_blocked_ipv4_mapped_loopback():
    # ::ffff:127.0.0.1 — an IPv4-mapped IPv6 address pointing at loopback.
    assert _ip_blocked("::ffff:127.0.0.1") is True


# --- DNS-rebinding / IP-pin connect tests ----------------------------------
#
# These exercise fetch_url_text's connect path. The defense: resolve the host
# ONCE to a concrete IP, validate THAT IP, then make httpx connect to the
# pinned IP while preserving the original Host header + TLS SNI for the
# hostname. We capture exactly what the client is asked to connect to.


class _FakeResponse:
    """Minimal stand-in for an httpx streaming response."""

    def __init__(self, *, body: bytes, content_type: str = "text/plain", encoding: str = "utf-8"):
        self.is_redirect = False
        self.headers = {"content-type": content_type}
        self.encoding = encoding
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aiter_bytes(self):
        yield self._body


class _FakeRedirect:
    def __init__(self, location: str):
        self.is_redirect = True
        self.headers = {"location": location}
        self.encoding = "utf-8"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _RecordingClient:
    """Records every stream() call so tests can assert the pinned connect target."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def stream(self, method, url, *, headers=None, extensions=None, **kw):
        self.calls.append(
            {"method": method, "url": url, "headers": headers or {}, "extensions": extensions or {}}
        )
        return self._responses.pop(0)

    async def aclose(self):
        pass


async def test_connect_pins_validated_ip_not_rehostname(monkeypatch):
    """Rebinding defense: the connect URL host is the pinned IP, while the Host
    header + TLS SNI still carry the original hostname so the request routes and
    TLS verifies correctly. httpx must NOT be handed the hostname to re-resolve."""
    _patch_resolve(monkeypatch, "93.184.216.34")
    client = _RecordingClient([_FakeResponse(body=b"hello jd body")])

    out = await fetch_url_text("https://example.com/jobs/9", client=client)

    assert out == "hello jd body"
    assert len(client.calls) == 1
    call = client.calls[0]
    # Connect target is the validated IP, not the (re-resolvable) hostname.
    assert "93.184.216.34" in call["url"]
    assert "example.com" not in call["url"]
    # Path/query preserved on the pinned URL.
    assert call["url"].endswith("/jobs/9")
    # Host header preserves the original hostname for correct origin routing.
    assert call["headers"].get("Host") == "example.com"
    # TLS SNI / cert verification target stays the hostname.
    assert call["extensions"].get("sni_hostname") == "example.com"


@pytest.mark.parametrize("ip", ["127.0.0.1", "169.254.169.254", "10.0.0.1"])
async def test_fetch_rejects_private_resolution(monkeypatch, ip):
    """A hostname resolving to a private/loopback/link-local IP is rejected before
    any connect is attempted."""
    _patch_resolve(monkeypatch, ip)
    client = _RecordingClient([_FakeResponse(body=b"should never be read")])
    with pytest.raises(SsrfBlockedError):
        await fetch_url_text("https://evil.example.com/jd", client=client)
    assert client.calls == []  # never connected


async def test_redirect_to_private_host_is_rejected(monkeypatch):
    """Redirect target is re-resolved + re-validated; a private redirect is blocked."""

    def fake_getaddrinfo(host, *args, **kwargs):
        ip = "93.184.216.34" if host == "example.com" else "127.0.0.1"
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, None, None, "", (ip, 0))]

    monkeypatch.setattr(jd_fetch.socket, "getaddrinfo", fake_getaddrinfo)
    client = _RecordingClient(
        [_FakeRedirect("https://internal.example.org/secret"), _FakeResponse(body=b"never")]
    )
    with pytest.raises(SsrfBlockedError):
        await fetch_url_text("https://example.com/jd", client=client)
    # First hop connected to the public IP; second hop rejected before connecting.
    assert len(client.calls) == 1
    assert "93.184.216.34" in client.calls[0]["url"]


async def test_redirect_to_public_host_is_pinned(monkeypatch):
    """A redirect to another public host re-resolves + pins the new IP."""

    def fake_getaddrinfo(host, *args, **kwargs):
        ip = {"example.com": "93.184.216.34", "cdn.example.net": "151.101.1.1"}[host]
        return [(socket.AF_INET, None, None, "", (ip, 0))]

    monkeypatch.setattr(jd_fetch.socket, "getaddrinfo", fake_getaddrinfo)
    client = _RecordingClient(
        [
            _FakeRedirect("https://cdn.example.net/real/jd"),
            _FakeResponse(body=b"final jd body"),
        ]
    )
    out = await fetch_url_text("https://example.com/jd", client=client)
    assert out == "final jd body"
    assert len(client.calls) == 2
    assert "93.184.216.34" in client.calls[0]["url"]
    assert client.calls[0]["headers"].get("Host") == "example.com"
    assert "151.101.1.1" in client.calls[1]["url"]
    assert client.calls[1]["headers"].get("Host") == "cdn.example.net"
    assert client.calls[1]["extensions"].get("sni_hostname") == "cdn.example.net"
