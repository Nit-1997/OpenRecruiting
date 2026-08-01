"""MCP-specific test fixtures.

We generate a fresh RSA keypair per test session, inject it into the
settings, and stub the Supabase service-layer calls so the OAuth flow can
be tested end-to-end without a real database.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Inject MCP env BEFORE the app config is loaded.
_PRIV = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIV_PEM = _PRIV.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode("utf-8")

os.environ["MCP_JWT_PRIVATE_KEY_PEM"] = _PRIV_PEM
os.environ["MCP_JWT_KEY_ID"] = "test-key-1"
os.environ["MCP_JWT_ISSUER"] = "http://testserver"
os.environ["MCP_ALLOWED_AUDIENCES"] = "cortex-mcp"
os.environ["APP_URL"] = "http://localhost:3004"
# Force the dev inline-consent path. v2 loads a real .env that sets
# MCP_CONSENT_URL (production redirect); these flow tests drive the inline
# form + /authorize/decision directly, matching v1's test environment.
os.environ["MCP_CONSENT_URL"] = ""


# Clear the settings cache so the test MCP env above is what get_settings()
# returns, then reset the JWT signer cache so it picks up the test key.
from app.config import get_settings  # noqa: E402
from app.services.mcp import jwt_signer  # noqa: E402

get_settings.cache_clear()
jwt_signer.reset_key_cache()


# ---------------------------------------------------------------------------
# In-memory stubs for the three service-layer stores
# ---------------------------------------------------------------------------

@dataclass
class _InMemoryClient:
    client_id: str
    client_name: str | None
    redirect_uris: list[str]
    grant_types: list[str]
    response_types: list[str]
    token_endpoint_auth_method: str
    scope: str


@dataclass
class _InMemoryCode:
    code: str
    client_id: str
    user_id: str
    organization_id: str | None
    redirect_uri: str
    scope: str
    audience: str
    code_challenge: str
    code_challenge_method: str
    consumed: bool
    expires_at: datetime


@dataclass
class _InMemoryRefreshToken:
    token: str
    token_hash: str
    client_id: str
    user_id: str
    organization_id: str | None
    scope: str
    audience: str
    expires_at: datetime
    revoked: bool = False


@dataclass
class _Stores:
    clients: dict[str, _InMemoryClient] = field(default_factory=dict)
    codes: dict[str, _InMemoryCode] = field(default_factory=dict)
    refresh_tokens: dict[str, _InMemoryRefreshToken] = field(default_factory=dict)


@pytest.fixture
def stores(monkeypatch) -> _Stores:
    """Replace each service-layer store with in-memory implementations."""
    s = _Stores()

    from app.services.mcp import client_store, code_store, refresh_store
    import secrets
    import hashlib

    # --- client_store ---
    async def register_client(*, client_name, redirect_uris, grant_types=None,
                              response_types=None, token_endpoint_auth_method="none",
                              scope="cortex:read", software_id=None, software_version=None):
        for uri in redirect_uris:
            if not (uri.startswith("https://") or uri.startswith("http://localhost") or uri.startswith("http://127.0.0.1")):
                raise ValueError(f"redirect_uri must be https:// or http://localhost (got {uri!r})")
        bad_grants = set(grant_types or ["authorization_code", "refresh_token"]) - {"authorization_code", "refresh_token"}
        if bad_grants:
            raise ValueError(f"Unsupported grant_types: {sorted(bad_grants)}")
        if token_endpoint_auth_method not in {"none", "client_secret_basic"}:
            raise ValueError(f"Unsupported token_endpoint_auth_method: {token_endpoint_auth_method!r}.")
        cid = f"mcp_{secrets.token_urlsafe(24)}"
        c = _InMemoryClient(
            client_id=cid,
            client_name=client_name,
            redirect_uris=list(redirect_uris),
            grant_types=list(grant_types or ["authorization_code", "refresh_token"]),
            response_types=list(response_types or ["code"]),
            token_endpoint_auth_method=token_endpoint_auth_method,
            scope=scope or "cortex:read",
        )
        s.clients[cid] = c
        return c

    async def get_client(cid):
        return s.clients.get(cid)

    monkeypatch.setattr(client_store, "register_client", register_client)
    monkeypatch.setattr(client_store, "get_client", get_client)
    monkeypatch.setattr(
        client_store, "validate_redirect_uri",
        lambda client, uri: uri in client.redirect_uris,
    )

    # --- code_store ---
    async def issue_code(*, client_id, user_id, organization_id, redirect_uri,
                         scope, audience, code_challenge, code_challenge_method="S256"):
        code_val = secrets.token_urlsafe(32)
        rec = _InMemoryCode(
            code=code_val, client_id=client_id, user_id=user_id,
            organization_id=organization_id, redirect_uri=redirect_uri, scope=scope,
            audience=audience, code_challenge=code_challenge,
            code_challenge_method=code_challenge_method, consumed=False,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=300),
        )
        s.codes[code_val] = rec
        return rec

    async def consume_code(code_val):
        rec = s.codes.get(code_val)
        if rec is None or rec.consumed:
            return None
        if rec.expires_at <= datetime.now(timezone.utc):
            return None
        rec.consumed = True
        return rec

    monkeypatch.setattr(code_store, "issue_code", issue_code)
    monkeypatch.setattr(code_store, "consume_code", consume_code)

    # --- refresh_store ---
    async def issue_refresh_token(*, client_id, user_id, organization_id, scope,
                                  audience, ttl_seconds=30 * 24 * 3600):
        tok = secrets.token_urlsafe(48)
        h = hashlib.sha256(tok.encode()).hexdigest()
        rec = _InMemoryRefreshToken(
            token=tok, token_hash=h, client_id=client_id, user_id=user_id,
            organization_id=organization_id, scope=scope, audience=audience,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        )
        s.refresh_tokens[h] = rec
        return rec

    async def use_refresh_token(tok, *, client_id):
        h = hashlib.sha256(tok.encode()).hexdigest()
        rec = s.refresh_tokens.get(h)
        if rec is None or rec.revoked:
            return None
        if rec.client_id != client_id:
            return None
        if rec.expires_at <= datetime.now(timezone.utc):
            return None
        rec.revoked = True
        return rec

    async def revoke_refresh_token(tok):
        h = hashlib.sha256(tok.encode()).hexdigest()
        rec = s.refresh_tokens.get(h)
        if rec is None or rec.revoked:
            return False
        rec.revoked = True
        return True

    monkeypatch.setattr(refresh_store, "issue_refresh_token", issue_refresh_token)
    monkeypatch.setattr(refresh_store, "use_refresh_token", use_refresh_token)
    monkeypatch.setattr(refresh_store, "revoke_refresh_token", revoke_refresh_token)

    # --- session resolver + claim loader (no Supabase) ---
    from app.api.v2.routers import mcp_oauth as oauth_mod
    from app.dependencies import CurrentUser
    from uuid import UUID
    from tests.helpers.mock_data import RECRUITER_USER_ID, RECRUITER_EMAIL, ORG_ID

    async def fake_resolve(request):
        # If the request carries an Authorization header or sb-access-token
        # cookie we treat it as the recruiter user. Otherwise raise to
        # exercise the redirect-to-login branch.
        auth = request.headers.get("Authorization")
        cookie = request.cookies.get("sb-access-token")
        if not auth and not cookie:
            raise oauth_mod._NotAuthenticated
        return CurrentUser(
            id=UUID(RECRUITER_USER_ID),
            email=RECRUITER_EMAIL,
            is_staff=False,
            organization_id=UUID(ORG_ID),
        )

    monkeypatch.setattr(oauth_mod, "_resolve_session_user", fake_resolve)

    async def fake_org_ctx(user):
        return (str(user.organization_id) if user.organization_id else None,
                "Test Org",
                user.email)

    monkeypatch.setattr(oauth_mod, "_load_user_org_context", fake_org_ctx)

    async def fake_claim_ctx(user_id, org_id):
        return ("Test Org", "Test Recruiter", "admin")

    monkeypatch.setattr(oauth_mod, "_load_token_claim_context", fake_claim_ctx)

    # Default current-membership stub: matches whatever org_id is stored on
    # the refresh token row for the recruiter user. Individual tests can
    # override this via monkeypatch to simulate offboarding, org-switch,
    # or profile deletion.
    s.membership_override = None  # type: ignore[attr-defined]

    async def fake_current_membership(user_id):
        override = getattr(s, "membership_override", None)
        if override == "DELETED":
            return None
        if override is not None:
            return oauth_mod._CurrentMembership(org_id=override)
        return oauth_mod._CurrentMembership(org_id=ORG_ID)

    monkeypatch.setattr(oauth_mod, "_load_current_membership", fake_current_membership)

    return s


@pytest.fixture
def pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE flow tests."""
    import base64
    import hashlib
    import secrets

    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge
