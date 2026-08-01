"""Tests for POST /api/v2/internal/cortex/service-token and the token minter.

Verifies the minted token is a real RS256 JWT with the claim shape Cortex MCP
requires (sub, org_id, aud=cortex-mcp, scope=cortex:read, kid header), and that
the endpoint enforces the internal secret and a real org.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.main import app
from app.services.mcp import jwt_signer, token_minter

ENDPOINT = "/api/v2/internal/cortex/service-token"
ORG_ID = "33333333-3333-3333-3333-333333333333"
SECRET = "super-secret"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode("utf-8")
_PUBLIC_KEY = _KEY.public_key()


def _fake_settings():
    return SimpleNamespace(
        MCP_JWT_PRIVATE_KEY_PEM=_PRIVATE_PEM,
        MCP_JWT_KEY_ID="test-kid",
        MCP_JWT_ISSUER="http://localhost:8004",
        MCP_ALLOWED_AUDIENCES="cortex-mcp",
        INTERNAL_API_SECRET=SECRET,
    )


@pytest.fixture(autouse=True)
def _reset_key_cache():
    jwt_signer._load_private_key.cache_clear()
    jwt_signer._public_key.cache_clear()
    yield
    jwt_signer._load_private_key.cache_clear()
    jwt_signer._public_key.cache_clear()
    app.dependency_overrides.clear()


def test_minter_produces_verifiable_cortex_token():
    with patch.object(token_minter, "get_settings", _fake_settings), \
         patch.object(jwt_signer, "get_settings", _fake_settings):
        token, ttl = token_minter.mint_cortex_service_token(org_id=ORG_ID, org_name="Acme")

    assert ttl == 300
    assert jwt.get_unverified_header(token)["kid"] == "test-kid"
    claims = jwt.decode(token, _PUBLIC_KEY, algorithms=["RS256"], audience="cortex-mcp")
    assert claims["org_id"] == ORG_ID
    assert claims["org_name"] == "Acme"
    assert claims["scope"] == "cortex:read"
    assert claims["iss"] == "http://localhost:8004"
    assert claims["sub"]


def _override_supabase(org_row):
    sb = MagicMock()
    # The route awaits execute_async(); a plain MagicMock here raises
    # "object MagicMock can't be used in 'await' expression".
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute_async = AsyncMock(
        return_value=MagicMock(data=org_row)
    )
    from app.api.v2.core.dependencies import get_supabase
    app.dependency_overrides[get_supabase] = lambda: sb
    return sb


def test_endpoint_happy_path():
    # The internal-secret guard now reads settings via the shared dependency in
    # app.api.v2.core.dependencies, so the secret patch targets that module.
    _override_supabase({"id": ORG_ID, "name": "Acme"})
    with patch.object(token_minter, "get_settings", _fake_settings), \
         patch.object(jwt_signer, "get_settings", _fake_settings), \
         patch("app.api.v2.core.dependencies.get_settings", _fake_settings):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(ENDPOINT, headers={"X-Internal-Secret": SECRET}, json={"organization_id": ORG_ID})
    assert resp.status_code == 200
    assert resp.json()["token"]
    assert resp.json()["expires_in"] == 300


def test_endpoint_rejects_bad_secret():
    _override_supabase({"id": ORG_ID, "name": "Acme"})
    with patch("app.api.v2.core.dependencies.get_settings", _fake_settings):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(ENDPOINT, headers={"X-Internal-Secret": "wrong"}, json={"organization_id": ORG_ID})
    assert resp.status_code == 401


def test_endpoint_404_when_org_missing():
    _override_supabase(None)
    with patch("app.api.v2.core.dependencies.get_settings", _fake_settings):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(ENDPOINT, headers={"X-Internal-Secret": SECRET}, json={"organization_id": ORG_ID})
    assert resp.status_code == 404
