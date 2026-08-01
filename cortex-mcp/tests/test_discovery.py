"""HTTP-level tests for OAuth discovery.

These tests use the actual FastAPI ASGI app so we exercise the Bearer-gate
middleware end-to-end, not just the tool layer.

We deliberately scope env overrides to a fixture so we don't pollute
neighboring test files (test_auth_contract.py imports env at module load
and expects its own values to win).
"""
from __future__ import annotations

import os

import pytest
from starlette.testclient import TestClient


_OVERRIDES = {
    "NEO4J_URI": "neo4j+s://placeholder",
    "NEO4J_USERNAME": "placeholder",
    "NEO4J_PASSWORD": "placeholder",
    "NEO4J_DATABASE": "placeholder",
    "OIDC_ISSUER": "http://testserver-auth",
    "OIDC_JWKS_URL": "http://testserver-auth/.well-known/jwks.json",
    "OIDC_AUDIENCE": "cortex-mcp",
    "CORTEX_PUBLIC_URL": "https://cortex.example.test",
    "OIDC_METADATA_URL": "",
}


@pytest.fixture(autouse=True)
def _env_and_stubs(monkeypatch):
    """Set env, stub Neo4j lifespan hooks, clear settings cache. Reverted
    automatically when monkeypatch teardown runs."""
    for k, v in _OVERRIDES.items():
        monkeypatch.setenv(k, v)

    from src.config.settings import get_settings

    get_settings.cache_clear()

    async def _noop() -> None:
        return None

    import src.main as main_mod

    monkeypatch.setattr(main_mod, "init_driver", _noop)
    monkeypatch.setattr(main_mod, "close_driver", _noop)
    yield
    get_settings.cache_clear()


@pytest.fixture
def app():
    from src.main import app as _app
    return _app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "cortex-mcp"}


def test_protected_resource_metadata_shape(client):
    r = client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    body = r.json()
    assert body["resource"] == "https://cortex.example.test"
    assert body["authorization_servers"] == ["http://testserver-auth"]
    assert body["bearer_methods_supported"] == ["header"]
    assert "cortex:read" in body["scopes_supported"]


def test_protected_resource_metadata_is_public(client):
    """Discovery must NOT require auth — that's the whole point."""
    r = client.get(
        "/.well-known/oauth-protected-resource",
        headers={"Authorization": "Bearer obviously-bad"},
    )
    assert r.status_code == 200


def test_mcp_unauthenticated_returns_401_with_resource_metadata(client):
    """The MCP spec requires the resource server to advertise the resource_
    metadata URL in WWW-Authenticate so OAuth clients can discover the auth
    server. This is the critical contract for Claude Desktop / Code /
    Inspector."""
    r = client.post("/mcp/", json={"jsonrpc": "2.0", "method": "initialize", "id": 1})
    assert r.status_code == 401, r.text
    www_auth = r.headers["WWW-Authenticate"]
    assert www_auth.startswith("Bearer ")
    assert 'realm="cortex-mcp"' in www_auth
    assert 'error="invalid_token"' in www_auth
    assert (
        'resource_metadata="https://cortex.example.test/.well-known/oauth-protected-resource"'
        in www_auth
    )


def test_mcp_path_without_trailing_slash_also_401s(client):
    """Claude Desktop sometimes posts to /mcp (no trailing slash). The 401
    must fire there too — otherwise a 404 leaks before the OAuth handshake.

    Critically, this must be a real 401 (not a 307 redirect to /mcp/) —
    307 strips the POST body in many MCP clients, including Claude Desktop,
    which then sees the connection as "silently failed".
    """
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
        follow_redirects=False,
    )
    assert r.status_code == 401, (
        f"Expected 401 for /mcp (no slash); got {r.status_code}. "
        f"If this is a 307, the bearer-gate middleware isn't rewriting the path."
    )
    assert "WWW-Authenticate" in r.headers


def test_mcp_path_without_trailing_slash_with_bearer_does_not_redirect(client):
    """With a Bearer header, /mcp (no slash) must reach FastMCP directly,
    not 307 → /mcp/. The redirect would lose the POST body."""
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
        headers={"Authorization": "Bearer anything"},
        follow_redirects=False,
    )
    assert r.status_code != 307, (
        "Bearer-authed POST to /mcp must not 307-redirect to /mcp/"
    )


def test_authenticated_path_falls_through_to_fastmcp(client):
    """When a Bearer header is present the gate steps aside and the request
    reaches FastMCP. The gate's WWW-Authenticate header must NOT appear on
    whatever downstream response we get."""
    r = client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
        headers={"Authorization": "Bearer anything"},
    )
    if r.status_code == 401:
        assert "WWW-Authenticate" not in r.headers, (
            "401 from a downstream layer must not carry the gate's "
            "WWW-Authenticate header"
        )


def test_metadata_url_override_takes_precedence(monkeypatch, client):
    """When OIDC_METADATA_URL is set, use it instead of issuer."""
    monkeypatch.setenv("OIDC_METADATA_URL", "https://other-auth.example/")
    from src.config.settings import get_settings
    get_settings.cache_clear()

    r = client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    assert r.json()["authorization_servers"] == ["https://other-auth.example"]
