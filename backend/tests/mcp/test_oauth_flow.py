"""End-to-end OAuth 2.1 flow tests for the MCP authorization server.

Covers:
  * Discovery endpoints (.well-known/oauth-authorization-server, jwks)
  * Dynamic Client Registration (RFC 7591) — happy + edge cases
  * Authorization code flow with PKCE (S256)
  * Token endpoint: code grant + refresh grant + rotation
  * Revocation
  * Tenancy & exfiltration: tokens carry the user's org_id, refresh tokens are
    bound to client_id (cannot be replayed cross-client), codes single-use
  * Signature validation: tokens verify against the published JWKS
"""
from __future__ import annotations

import json
import time

import jwt as jose_jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from fastapi.testclient import TestClient

from app.main import app


REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"


@pytest.fixture
def client(stores) -> TestClient:
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _register_client(client: TestClient, **overrides) -> dict:
    body = {
        "client_name": "Claude.ai",
        "redirect_uris": [REDIRECT_URI],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": "cortex:read",
    }
    body.update(overrides)
    resp = client.post("/api/v2/mcp/oauth/register", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _auth_code_via_consent(
    client: TestClient,
    client_id: str,
    challenge: str,
    *,
    scope: str = "cortex:read",
    state: str = "xyz",
    audience: str = "cortex-mcp",
) -> str:
    """Drive /authorize + /authorize/decision and return the issued code."""
    # GET — render consent page (logged-in user)
    r = client.get(
        "/api/v2/mcp/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": scope,
            "state": state,
            "resource": audience,
        },
        headers={"Authorization": "Bearer fake-supabase-session"},
    )
    assert r.status_code == 200
    assert "Allow" in r.text

    # POST allow decision
    r = client.post(
        "/api/v2/mcp/oauth/authorize/decision",
        data={
            "decision": "allow",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": scope,
            "state": state,
            "audience": audience,
        },
        headers={"Authorization": "Bearer fake-supabase-session"},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    location = r.headers["location"]
    assert location.startswith(REDIRECT_URI)
    # Extract `code=...&state=...`
    qs = dict(part.split("=", 1) for part in location.split("?", 1)[1].split("&"))
    assert qs.get("state") == state
    return qs["code"]


# ---------------------------------------------------------------------------
# Discovery + JWKS
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_authorization_server_metadata_shape(self, client: TestClient) -> None:
        r = client.get("/.well-known/oauth-authorization-server")
        assert r.status_code == 200
        meta = r.json()
        assert meta["issuer"] == "http://testserver"
        assert meta["authorization_endpoint"].endswith("/api/v2/mcp/oauth/authorize")
        assert meta["token_endpoint"].endswith("/api/v2/mcp/oauth/token")
        assert meta["registration_endpoint"].endswith("/api/v2/mcp/oauth/register")
        assert meta["jwks_uri"].endswith("/.well-known/jwks.json")
        assert "S256" in meta["code_challenge_methods_supported"]
        assert "authorization_code" in meta["grant_types_supported"]
        assert "refresh_token" in meta["grant_types_supported"]

    def test_jwks_published_with_public_key(self, client: TestClient) -> None:
        r = client.get("/.well-known/jwks.json")
        assert r.status_code == 200
        body = r.json()
        assert len(body["keys"]) == 1
        k = body["keys"][0]
        assert k["kty"] == "RSA"
        assert k["alg"] == "RS256"
        assert k["use"] == "sig"
        assert k["kid"] == "test-key-1"
        assert k["n"]
        assert k["e"]

    def test_jwks_cache_control_header_set(self, client: TestClient) -> None:
        r = client.get("/.well-known/jwks.json")
        assert "Cache-Control" in r.headers
        assert "max-age" in r.headers["Cache-Control"]


# ---------------------------------------------------------------------------
# Dynamic Client Registration (RFC 7591)
# ---------------------------------------------------------------------------

class TestRegister:
    def test_happy_path(self, client: TestClient) -> None:
        body = _register_client(client)
        assert body["client_id"].startswith("mcp_")
        assert body["client_name"] == "Claude.ai"
        assert body["redirect_uris"] == [REDIRECT_URI]
        assert "authorization_code" in body["grant_types"]
        assert body["token_endpoint_auth_method"] == "none"

    def test_missing_redirect_uris_rejected(self, client: TestClient, stores) -> None:
        r = client.post(
            "/api/v2/mcp/oauth/register",
            json={"client_name": "Bad", "redirect_uris": []},
        )
        assert r.status_code == 422  # pydantic min_length=1

    def test_non_https_redirect_rejected(self, client: TestClient, stores) -> None:
        r = client.post(
            "/api/v2/mcp/oauth/register",
            json={"client_name": "Bad", "redirect_uris": ["http://evil.com/cb"]},
        )
        assert r.status_code == 400
        assert "https" in r.json()["detail"]

    def test_localhost_redirect_allowed(self, client: TestClient, stores) -> None:
        r = client.post(
            "/api/v2/mcp/oauth/register",
            json={"client_name": "Local", "redirect_uris": ["http://localhost:54321/cb"]},
        )
        assert r.status_code == 201

    def test_unsupported_grant_type_rejected(self, client: TestClient, stores) -> None:
        r = client.post(
            "/api/v2/mcp/oauth/register",
            json={
                "client_name": "Bad",
                "redirect_uris": [REDIRECT_URI],
                "grant_types": ["client_credentials"],
            },
        )
        assert r.status_code == 400
        assert "client_credentials" in r.json()["detail"]

    def test_client_secret_grants_rejected(self, client: TestClient, stores) -> None:
        r = client.post(
            "/api/v2/mcp/oauth/register",
            json={
                "client_name": "Confidential",
                "redirect_uris": [REDIRECT_URI],
                "token_endpoint_auth_method": "client_secret_post",
            },
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Authorization endpoint
# ---------------------------------------------------------------------------

class TestClientMetadataLookup:
    def test_returns_display_safe_fields(self, client: TestClient, stores) -> None:
        body = _register_client(client, client_name="Claude.ai")
        r = client.get(f"/api/v2/mcp/oauth/clients/{body['client_id']}")
        assert r.status_code == 200
        meta = r.json()
        assert meta["client_id"] == body["client_id"]
        assert meta["client_name"] == "Claude.ai"
        assert meta["redirect_uris"] == [REDIRECT_URI]
        # No software_id, software_version, or auth-method internals exposed
        assert "software_id" not in meta
        assert "token_endpoint_auth_method" not in meta

    def test_unknown_client_returns_404(self, client: TestClient, stores) -> None:
        r = client.get("/api/v2/mcp/oauth/clients/mcp_does_not_exist")
        assert r.status_code == 404


class TestAuthorize:
    def test_unauthenticated_user_redirects_to_login(
        self, client: TestClient, stores, pkce_pair
    ) -> None:
        body = _register_client(client)
        _verifier, challenge = pkce_pair
        r = client.get(
            "/api/v2/mcp/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": body["client_id"],
                "redirect_uri": REDIRECT_URI,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "cortex:read",
                "state": "abc",
            },
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert "/login" in r.headers["location"]

    def test_authenticated_user_sees_consent_screen(
        self, client: TestClient, stores, pkce_pair
    ) -> None:
        body = _register_client(client)
        _verifier, challenge = pkce_pair
        r = client.get(
            "/api/v2/mcp/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": body["client_id"],
                "redirect_uri": REDIRECT_URI,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "cortex:read",
                "state": "abc",
            },
            headers={"Authorization": "Bearer fake-supabase-session"},
        )
        assert r.status_code == 200
        assert "Claude.ai" in r.text
        assert "cortex:read" in r.text or "recruitment-intelligence" in r.text
        assert "Allow" in r.text

    def test_unknown_client_id_rejected(
        self, client: TestClient, stores, pkce_pair
    ) -> None:
        _verifier, challenge = pkce_pair
        r = client.get(
            "/api/v2/mcp/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": "mcp_unknown",
                "redirect_uri": REDIRECT_URI,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            headers={"Authorization": "Bearer fake-supabase-session"},
        )
        assert r.status_code == 401
        assert r.json()["error"] == "invalid_client"

    def test_wrong_redirect_uri_rejected(
        self, client: TestClient, stores, pkce_pair
    ) -> None:
        body = _register_client(client)
        _verifier, challenge = pkce_pair
        r = client.get(
            "/api/v2/mcp/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": body["client_id"],
                "redirect_uri": "https://evil.com/cb",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            headers={"Authorization": "Bearer fake-supabase-session"},
        )
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_request"

    def test_plain_pkce_rejected(self, client: TestClient, stores) -> None:
        body = _register_client(client)
        r = client.get(
            "/api/v2/mcp/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": body["client_id"],
                "redirect_uri": REDIRECT_URI,
                "code_challenge": "x" * 43,
                "code_challenge_method": "plain",
            },
            headers={"Authorization": "Bearer fake-supabase-session"},
        )
        assert r.status_code == 400
        assert "S256" in r.json()["error_description"]

    def test_unknown_audience_rejected(
        self, client: TestClient, stores, pkce_pair
    ) -> None:
        body = _register_client(client)
        _verifier, challenge = pkce_pair
        r = client.get(
            "/api/v2/mcp/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": body["client_id"],
                "redirect_uri": REDIRECT_URI,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": "not-cortex",
            },
            headers={"Authorization": "Bearer fake-supabase-session"},
        )
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_target"

    def test_authorize_redirects_to_consent_url_when_configured(
        self, client: TestClient, stores, pkce_pair, monkeypatch
    ) -> None:
        """When MCP_CONSENT_URL is set, /authorize hands off to that URL with
        all OAuth params preserved. The consent UI then handles session +
        decision capture."""
        monkeypatch.setenv("MCP_CONSENT_URL", "http://localhost:3000/oauth/consent")
        from app.config import get_settings
        get_settings.cache_clear()
        try:
            body = _register_client(client)
            _verifier, challenge = pkce_pair
            r = client.get(
                "/api/v2/mcp/oauth/authorize",
                params={
                    "response_type": "code",
                    "client_id": body["client_id"],
                    "redirect_uri": REDIRECT_URI,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "scope": "cortex:read",
                    "state": "abc",
                },
                follow_redirects=False,
            )
            assert r.status_code == 302
            loc = r.headers["location"]
            assert loc.startswith("http://localhost:3000/oauth/consent?")
            assert f"client_id={body['client_id']}" in loc
            assert "code_challenge=" in loc
            assert "state=abc" in loc
            assert "audience=cortex-mcp" in loc
            # The validated audience should be present in the forwarded URL —
            # the consent page doesn't have to know our allowlist.
        finally:
            get_settings.cache_clear()

    def test_authorize_validates_before_redirecting_to_consent(
        self, client: TestClient, stores, pkce_pair, monkeypatch
    ) -> None:
        """Validation (response_type, PKCE method, client_id) must run BEFORE
        the redirect, so a bad MCP client never reaches the consent UI."""
        monkeypatch.setenv("MCP_CONSENT_URL", "http://localhost:3000/oauth/consent")
        from app.config import get_settings
        get_settings.cache_clear()
        try:
            r = client.get(
                "/api/v2/mcp/oauth/authorize",
                params={
                    "response_type": "code",
                    "client_id": "mcp_does_not_exist",
                    "redirect_uri": REDIRECT_URI,
                    "code_challenge": "x" * 43,
                    "code_challenge_method": "S256",
                },
            )
            # Should reject (401), not redirect to consent
            assert r.status_code == 401
            assert r.json()["error"] == "invalid_client"
        finally:
            get_settings.cache_clear()

    def test_deny_redirects_with_error(
        self, client: TestClient, stores, pkce_pair
    ) -> None:
        body = _register_client(client)
        _verifier, challenge = pkce_pair
        r = client.post(
            "/api/v2/mcp/oauth/authorize/decision",
            data={
                "decision": "deny",
                "client_id": body["client_id"],
                "redirect_uri": REDIRECT_URI,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "cortex:read",
                "state": "abc",
                "audience": "cortex-mcp",
            },
            headers={"Authorization": "Bearer fake-supabase-session"},
            follow_redirects=False,
        )
        assert r.status_code == 302
        loc = r.headers["location"]
        assert "error=access_denied" in loc
        assert "state=abc" in loc


# ---------------------------------------------------------------------------
# Token endpoint — authorization_code grant
# ---------------------------------------------------------------------------

class TestTokenAuthorizationCode:
    def test_full_happy_path(self, client: TestClient, stores, pkce_pair) -> None:
        body = _register_client(client)
        verifier, challenge = pkce_pair
        code = _auth_code_via_consent(client, body["client_id"], challenge)

        r = client.post(
            "/api/v2/mcp/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": body["client_id"],
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
            },
        )
        assert r.status_code == 200, r.text
        tok = r.json()
        assert tok["token_type"] == "Bearer"
        assert tok["expires_in"] == 3600
        assert tok["access_token"]
        assert tok["refresh_token"]
        assert tok["scope"] == "cortex:read"

    def test_code_is_single_use(self, client: TestClient, stores, pkce_pair) -> None:
        body = _register_client(client)
        verifier, challenge = pkce_pair
        code = _auth_code_via_consent(client, body["client_id"], challenge)

        first = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "authorization_code",
            "client_id": body["client_id"],
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        })
        assert first.status_code == 200

        second = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "authorization_code",
            "client_id": body["client_id"],
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        })
        assert second.status_code == 400
        assert second.json()["error"] == "invalid_grant"

    def test_wrong_code_verifier_rejected(
        self, client: TestClient, stores, pkce_pair
    ) -> None:
        body = _register_client(client)
        _verifier, challenge = pkce_pair
        code = _auth_code_via_consent(client, body["client_id"], challenge)

        r = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "authorization_code",
            "client_id": body["client_id"],
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": "x" * 64,
        })
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_grant"

    def test_code_bound_to_client_id(
        self, client: TestClient, stores, pkce_pair
    ) -> None:
        body_a = _register_client(client, client_name="App A")
        body_b = _register_client(client, client_name="App B")
        verifier, challenge = pkce_pair
        code = _auth_code_via_consent(client, body_a["client_id"], challenge)

        r = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "authorization_code",
            "client_id": body_b["client_id"],
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        })
        assert r.status_code == 400
        assert "different client" in r.json()["error_description"].lower()

    def test_redirect_uri_mismatch_rejected(
        self, client: TestClient, stores, pkce_pair
    ) -> None:
        body = _register_client(client)
        verifier, challenge = pkce_pair
        code = _auth_code_via_consent(client, body["client_id"], challenge)

        r = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "authorization_code",
            "client_id": body["client_id"],
            "code": code,
            "redirect_uri": "https://other.example/cb",
            "code_verifier": verifier,
        })
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_grant"

    def test_access_token_carries_org_id_and_audience(
        self, client: TestClient, stores, pkce_pair
    ) -> None:
        body = _register_client(client)
        verifier, challenge = pkce_pair
        code = _auth_code_via_consent(client, body["client_id"], challenge)

        r = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "authorization_code",
            "client_id": body["client_id"],
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        })
        access = r.json()["access_token"]
        claims = _decode_with_jwks(client, access, audience="cortex-mcp")
        assert claims["aud"] == "cortex-mcp"
        assert claims["org_id"]
        assert claims["scope"] == "cortex:read"
        assert claims["org_name"] == "Test Org"
        assert claims["iss"] == "http://testserver"

    def test_missing_pkce_verifier_rejected(
        self, client: TestClient, stores, pkce_pair
    ) -> None:
        body = _register_client(client)
        _verifier, challenge = pkce_pair
        code = _auth_code_via_consent(client, body["client_id"], challenge)

        r = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "authorization_code",
            "client_id": body["client_id"],
            "code": code,
            "redirect_uri": REDIRECT_URI,
        })
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_request"


# ---------------------------------------------------------------------------
# Token endpoint — refresh_token grant
# ---------------------------------------------------------------------------

class TestRefresh:
    def _initial_pair(self, client, stores, pkce_pair):
        body = _register_client(client)
        verifier, challenge = pkce_pair
        code = _auth_code_via_consent(client, body["client_id"], challenge)
        first = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "authorization_code",
            "client_id": body["client_id"],
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        })
        return body["client_id"], first.json()

    def test_refresh_returns_new_access_and_refresh(self, client, stores, pkce_pair):
        cid, tok = self._initial_pair(client, stores, pkce_pair)
        r = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "refresh_token",
            "client_id": cid,
            "refresh_token": tok["refresh_token"],
        })
        assert r.status_code == 200
        new = r.json()
        assert new["access_token"]
        assert new["refresh_token"] and new["refresh_token"] != tok["refresh_token"]

    def test_refresh_rotates_token(self, client, stores, pkce_pair):
        cid, tok = self._initial_pair(client, stores, pkce_pair)
        r1 = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "refresh_token", "client_id": cid,
            "refresh_token": tok["refresh_token"],
        })
        assert r1.status_code == 200
        # Old token should now be revoked
        r2 = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "refresh_token", "client_id": cid,
            "refresh_token": tok["refresh_token"],
        })
        assert r2.status_code == 400
        assert r2.json()["error"] == "invalid_grant"

    def test_refresh_token_bound_to_client(self, client, stores, pkce_pair):
        cid_a, tok = self._initial_pair(client, stores, pkce_pair)
        body_b = _register_client(client, client_name="App B")
        r = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "refresh_token",
            "client_id": body_b["client_id"],
            "refresh_token": tok["refresh_token"],
        })
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_grant"

    def test_revoke_then_refresh_fails(self, client, stores, pkce_pair):
        cid, tok = self._initial_pair(client, stores, pkce_pair)
        rv = client.post("/api/v2/mcp/oauth/revoke", data={"token": tok["refresh_token"]})
        assert rv.status_code == 200
        r = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "refresh_token", "client_id": cid,
            "refresh_token": tok["refresh_token"],
        })
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Token signature verification (resource servers will do this)
# ---------------------------------------------------------------------------

class TestSignature:
    def test_signature_verifies_against_published_jwks(
        self, client, stores, pkce_pair
    ):
        body = _register_client(client)
        verifier, challenge = pkce_pair
        code = _auth_code_via_consent(client, body["client_id"], challenge)
        tok = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "authorization_code",
            "client_id": body["client_id"],
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        }).json()

        claims = _decode_with_jwks(client, tok["access_token"], audience="cortex-mcp")
        assert claims["sub"]
        assert claims["exp"] > int(time.time())
        assert claims["iat"] <= int(time.time())


# ---------------------------------------------------------------------------
# Misc / negative
# ---------------------------------------------------------------------------

class TestMisc:
    def test_unsupported_grant_type(self, client, stores):
        body = _register_client(client)
        r = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "password",
            "client_id": body["client_id"],
        })
        assert r.status_code == 400
        assert r.json()["error"] == "unsupported_grant_type"

    def test_token_unknown_client(self, client, stores):
        r = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "authorization_code",
            "client_id": "mcp_does_not_exist",
            "code": "x", "redirect_uri": REDIRECT_URI, "code_verifier": "y" * 64,
        })
        assert r.status_code == 401
        assert r.json()["error"] == "invalid_client"

    def test_revoke_is_always_200(self, client, stores):
        # Even for a token that never existed
        r = client.post("/api/v2/mcp/oauth/revoke", data={"token": "garbage"})
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Consent POST tampering — the form fields posted to /authorize/decision are
# attacker-controllable. The backend MUST re-validate every OAuth parameter
# (PKCE method, scope allowlist, audience allowlist, client registration,
# redirect_uri) on POST, not just trust the form. Otherwise an attacker can
# skip the GET-side audience/PKCE/scope guards and have us sign tokens for
# unvalidated values.
# ---------------------------------------------------------------------------

class TestConsentTamperingRejected:
    def _baseline_form(self, client_id: str, challenge: str) -> dict[str, str]:
        return {
            "decision": "allow",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "cortex:read",
            "state": "xyz",
            "audience": "cortex-mcp",
        }

    def test_tampered_audience_rejected(self, client: TestClient, stores, pkce_pair):
        _, challenge = pkce_pair
        body = _register_client(client)
        form = self._baseline_form(body["client_id"], challenge)
        form["audience"] = "https://evil.example.com"

        r = client.post(
            "/api/v2/mcp/oauth/authorize/decision",
            data=form,
            headers={"Authorization": "Bearer fake-supabase-session"},
            follow_redirects=False,
        )
        assert r.status_code == 400, r.text
        assert r.json()["error"] == "invalid_target"
        # And no code should have been issued.
        assert len(stores.codes) == 0

    def test_tampered_pkce_method_rejected(self, client: TestClient, stores, pkce_pair):
        _, challenge = pkce_pair
        body = _register_client(client)
        form = self._baseline_form(body["client_id"], challenge)
        form["code_challenge_method"] = "plain"

        r = client.post(
            "/api/v2/mcp/oauth/authorize/decision",
            data=form,
            headers={"Authorization": "Bearer fake-supabase-session"},
            follow_redirects=False,
        )
        assert r.status_code == 400, r.text
        assert r.json()["error"] == "invalid_request"
        assert "S256" in r.json()["error_description"]
        assert len(stores.codes) == 0

    def test_missing_code_challenge_rejected(self, client: TestClient, stores, pkce_pair):
        _, challenge = pkce_pair
        body = _register_client(client)
        form = self._baseline_form(body["client_id"], challenge)
        # Drop the field entirely. FastAPI's required-Form check fires first
        # (422), but the *security* property we care about — no code minted —
        # still holds. If a future refactor makes the field Optional, our
        # backend check still catches the empty value (400).
        del form["code_challenge"]

        r = client.post(
            "/api/v2/mcp/oauth/authorize/decision",
            data=form,
            headers={"Authorization": "Bearer fake-supabase-session"},
            follow_redirects=False,
        )
        assert r.status_code in (400, 422), r.text
        assert len(stores.codes) == 0

    def test_unknown_scope_rejected(self, client: TestClient, stores, pkce_pair):
        _, challenge = pkce_pair
        body = _register_client(client)
        form = self._baseline_form(body["client_id"], challenge)
        # cortex:write is not in the server's allowlist
        form["scope"] = "cortex:write"

        r = client.post(
            "/api/v2/mcp/oauth/authorize/decision",
            data=form,
            headers={"Authorization": "Bearer fake-supabase-session"},
            follow_redirects=False,
        )
        assert r.status_code == 400, r.text
        assert r.json()["error"] == "invalid_scope"
        assert len(stores.codes) == 0

    def test_unknown_client_id_rejected(self, client: TestClient, stores, pkce_pair):
        _, challenge = pkce_pair
        form = self._baseline_form("mcp_does_not_exist", challenge)

        r = client.post(
            "/api/v2/mcp/oauth/authorize/decision",
            data=form,
            headers={"Authorization": "Bearer fake-supabase-session"},
            follow_redirects=False,
        )
        assert r.status_code == 401, r.text
        assert r.json()["error"] == "invalid_client"
        assert len(stores.codes) == 0

    def test_redirect_uri_not_registered_rejected(self, client: TestClient, stores, pkce_pair):
        _, challenge = pkce_pair
        body = _register_client(client)
        form = self._baseline_form(body["client_id"], challenge)
        form["redirect_uri"] = "https://attacker.example.com/steal"

        r = client.post(
            "/api/v2/mcp/oauth/authorize/decision",
            data=form,
            headers={"Authorization": "Bearer fake-supabase-session"},
            follow_redirects=False,
        )
        # The bad redirect must be caught BEFORE we ever redirect to it.
        assert r.status_code == 400, r.text
        assert r.json()["error"] == "invalid_request"
        assert len(stores.codes) == 0

    def test_refresh_rejected_when_user_switched_org(self, client: TestClient, stores, pkce_pair):
        """A user removed from the consenting org cannot keep minting access
        tokens to the OLD org via their old refresh token."""
        verifier, challenge = pkce_pair
        body = _register_client(client)
        code = _auth_code_via_consent(client, body["client_id"], challenge)
        r = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "authorization_code",
            "client_id": body["client_id"],
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        })
        assert r.status_code == 200
        refresh_token = r.json()["refresh_token"]

        # Simulate the user being moved to a different org.
        stores.membership_override = "00000000-0000-0000-0000-000000000099"

        r = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "refresh_token",
            "client_id": body["client_id"],
            "refresh_token": refresh_token,
        })
        assert r.status_code == 400, r.text
        assert r.json()["error"] == "invalid_grant"
        # And the old refresh token must have been consumed by the attempt
        # — replay must also fail.
        r2 = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "refresh_token",
            "client_id": body["client_id"],
            "refresh_token": refresh_token,
        })
        assert r2.status_code == 400
        assert r2.json()["error"] == "invalid_grant"

    def test_refresh_rejected_when_profile_deleted(self, client: TestClient, stores, pkce_pair):
        """A soft-deleted user (profile.deleted_at IS NOT NULL or row gone)
        cannot refresh."""
        verifier, challenge = pkce_pair
        body = _register_client(client)
        code = _auth_code_via_consent(client, body["client_id"], challenge)
        r = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "authorization_code",
            "client_id": body["client_id"],
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        })
        assert r.status_code == 200
        refresh_token = r.json()["refresh_token"]

        stores.membership_override = "DELETED"

        r = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "refresh_token",
            "client_id": body["client_id"],
            "refresh_token": refresh_token,
        })
        assert r.status_code == 400, r.text
        assert r.json()["error"] == "invalid_grant"

    def test_refresh_rejected_when_org_set_null(self, client: TestClient, stores, pkce_pair):
        """If the user's org was deleted (ON DELETE SET NULL), their
        organization_id becomes NULL — mismatch with the stored org on the
        refresh token, so refresh must fail."""
        verifier, challenge = pkce_pair
        body = _register_client(client)
        code = _auth_code_via_consent(client, body["client_id"], challenge)
        r = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "authorization_code",
            "client_id": body["client_id"],
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        })
        assert r.status_code == 200
        refresh_token = r.json()["refresh_token"]

        # Simulate org deletion: profile still exists, organization_id is now NULL.
        # Sentinel value distinct from DELETED — must yield org_id=None.
        from app.api.v2.routers import mcp_oauth as oauth_mod

        async def membership_with_null_org(user_id):
            return oauth_mod._CurrentMembership(org_id=None)

        import pytest
        from tests.mcp import conftest  # noqa: F401  (loaded via pytest discovery)

        monkey = pytest.MonkeyPatch()
        monkey.setattr(oauth_mod, "_load_current_membership", membership_with_null_org)
        try:
            r = client.post("/api/v2/mcp/oauth/token", data={
                "grant_type": "refresh_token",
                "client_id": body["client_id"],
                "refresh_token": refresh_token,
            })
        finally:
            monkey.undo()

        assert r.status_code == 400, r.text
        assert r.json()["error"] == "invalid_grant"

    def test_refresh_succeeds_when_membership_unchanged(self, client: TestClient, stores, pkce_pair):
        """Baseline: matching org membership still rotates as before."""
        verifier, challenge = pkce_pair
        body = _register_client(client)
        code = _auth_code_via_consent(client, body["client_id"], challenge)
        r = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "authorization_code",
            "client_id": body["client_id"],
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        })
        assert r.status_code == 200
        refresh_token = r.json()["refresh_token"]

        # No override set — fake_current_membership returns ORG_ID, which
        # matches the org bound on the refresh token at authorize time.
        r = client.post("/api/v2/mcp/oauth/token", data={
            "grant_type": "refresh_token",
            "client_id": body["client_id"],
            "refresh_token": refresh_token,
        })
        assert r.status_code == 200, r.text
        body2 = r.json()
        assert "access_token" in body2
        assert "refresh_token" in body2

    def test_get_authorize_rejects_unknown_scope(self, client: TestClient, stores, pkce_pair):
        _, challenge = pkce_pair
        body = _register_client(client)
        r = client.get(
            "/api/v2/mcp/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": body["client_id"],
                "redirect_uri": REDIRECT_URI,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "cortex:admin",  # not in allowlist
                "resource": "cortex-mcp",
            },
            headers={"Authorization": "Bearer fake-supabase-session"},
        )
        assert r.status_code == 400, r.text
        assert r.json()["error"] == "invalid_scope"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_with_jwks(client: TestClient, token: str, *, audience: str) -> dict:
    """Verify token against the live JWKS endpoint, the way a resource server
    would. This proves the signing key and the published JWKS agree."""
    jwks = client.get("/.well-known/jwks.json").json()
    key = next(k for k in jwks["keys"] if k["kid"] == jose_jwt.get_unverified_header(token)["kid"])
    # Construct the public key from JWK n, e
    from jwt.algorithms import RSAAlgorithm

    public_key = RSAAlgorithm.from_jwk(json.dumps(key))
    return jose_jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        audience=audience,
        issuer="http://testserver",
    )
