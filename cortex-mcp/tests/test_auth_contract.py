"""Contract test: tokens minted by `backend` validate in `cortex-mcp`.

This test does NOT depend on either repo being running. It:
  1) Imports the JWT signer from backend (the producer)
  2) Patches Cortex MCP's JWKS cache with the producer's public key
  3) Verifies a freshly-signed access token round-trips through validate_token

If this test passes, the two services agree on:
  * algorithm (RS256)
  * issuer, audience, scope claim names
  * key publication format (JWK with kty, n, e, kid, alg, use)
  * AuthContext shape

The test is skipped automatically if the backend sources are not on
the Python path (e.g. when this repo is checked out standalone).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_BACKEND_SRC = Path(__file__).resolve().parents[2] / "backend"
if not _BACKEND_SRC.exists():
    pytest.skip("backend not present", allow_module_level=True)

sys.path.insert(0, str(_BACKEND_SRC))

# Bootstrap minimum env for backend's settings to load.
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SECRET_KEY", "dev-test-secret")
os.environ.setdefault("SUPABASE_JWT_SECRET", "x" * 32)
os.environ["MCP_JWT_ISSUER"] = "http://testserver"
os.environ["MCP_JWT_KEY_ID"] = "contract-test-key"
os.environ["MCP_ALLOWED_AUDIENCES"] = "cortex-mcp"

# Generate a dedicated keypair for this test.
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_PRIV = rsa.generate_private_key(public_exponent=65537, key_size=2048)
os.environ["MCP_JWT_PRIVATE_KEY_PEM"] = _PRIV.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode("utf-8")

# Cortex MCP env (verifier side)
os.environ["NEO4J_URI"] = "neo4j+s://placeholder"
os.environ["NEO4J_USERNAME"] = "placeholder"
os.environ["NEO4J_PASSWORD"] = "placeholder"
os.environ["OIDC_ISSUER"] = "http://testserver"
os.environ["OIDC_JWKS_URL"] = "http://testserver/.well-known/jwks.json"
os.environ["OIDC_AUDIENCE"] = "cortex-mcp"

# Now import both sides.
from app.services.mcp.jwt_signer import sign_access_token, public_jwks, reset_key_cache  # noqa: E402
from src.auth import jwt_validator   # noqa: E402
from src.config.settings import get_settings   # noqa: E402

reset_key_cache()
get_settings.cache_clear()


@pytest.fixture
def patched_jwks(monkeypatch):
    """Replace cortex-mcp's _fetch_jwks with the producer's public JWKS."""
    jwks = public_jwks()

    async def fake_fetch():
        return jwks

    monkeypatch.setattr(jwt_validator, "_fetch_jwks", fake_fetch)
    # Also wipe the module-level cache between tests.
    jwt_validator._JWKS_CACHE["keys"] = None
    jwt_validator._JWKS_CACHE["fetched_at"] = 0.0
    yield


async def test_token_minted_by_backend_validates_in_cortex_mcp(patched_jwks):
    signed = sign_access_token(
        subject="8c1a3c8f-2f3e-4d2b-9d4a-0f8e1b2c3d4e",
        audience="cortex-mcp",
        org_id="8f5311b7-7427-47c0-97d1-e1e6c4c23847",
        org_name="Acme",
        user_name="Nitin Bhat",
        role="admin",
        scope="cortex:read",
        ttl_seconds=600,
    )
    auth = await jwt_validator.validate_token(signed.token)
    assert auth.user_id == "8c1a3c8f-2f3e-4d2b-9d4a-0f8e1b2c3d4e"
    assert auth.org_id == "8f5311b7-7427-47c0-97d1-e1e6c4c23847"
    assert auth.org_name == "Acme"
    assert auth.user_name == "Nitin Bhat"
    assert auth.role == "admin"
    assert "cortex:read" in auth.scopes


async def test_token_for_wrong_audience_rejected(patched_jwks):
    signed = sign_access_token(
        subject="user-1",
        audience="some-other-mcp",
        org_id="org-1",
        org_name="X",
        user_name=None,
        role=None,
        scope="cortex:read",
    )
    with pytest.raises(jwt_validator.AuthError):
        await jwt_validator.validate_token(signed.token)


async def test_token_without_cortex_read_scope_rejected(patched_jwks):
    signed = sign_access_token(
        subject="user-1",
        audience="cortex-mcp",
        org_id="org-1",
        org_name="X",
        user_name=None,
        role=None,
        scope="some:other:scope",
    )
    with pytest.raises(jwt_validator.AuthError, match="cortex:read"):
        await jwt_validator.validate_token(signed.token)
