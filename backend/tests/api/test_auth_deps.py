"""
Tests for the shared auth dependencies introduced by BE-F3.

Covers:
- `app.dependencies._decode_supabase_jwt` — the single Supabase-JWT decoder
  used by both `get_current_user` and `get_authenticated_user_id`. It must
  decode HS256 and ES256 tokens identically to the old inline blocks and
  reject bad/expired tokens with a 401.
- `app.api.v2.core.dependencies.verify_internal_secret` — the shared
  X-Internal-Secret dependency that the internal routers will adopt later.
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from app.config import get_settings


# ---------------------------------------------------------------------------
# _decode_supabase_jwt — HS256
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decode_hs256_valid_token():
    from app.dependencies import _decode_supabase_jwt

    settings = get_settings()
    token = jwt.encode(
        {"sub": "user-123", "aud": "authenticated"},
        settings.SUPABASE_JWT_SECRET,
        algorithm="HS256",
    )

    payload = await _decode_supabase_jwt(token)
    assert payload["sub"] == "user-123"


@pytest.mark.asyncio
async def test_decode_rejects_garbage_token():
    from app.dependencies import _decode_supabase_jwt

    with pytest.raises(HTTPException) as exc:
        await _decode_supabase_jwt("not-a-jwt")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_decode_rejects_expired_hs256_token():
    from app.dependencies import _decode_supabase_jwt

    settings = get_settings()
    token = jwt.encode(
        {
            "sub": "user-123",
            "aud": "authenticated",
            "exp": int(time.time()) - 60,
        },
        settings.SUPABASE_JWT_SECRET,
        algorithm="HS256",
    )

    with pytest.raises(HTTPException) as exc:
        await _decode_supabase_jwt(token)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_decode_rejects_hs256_wrong_secret():
    from app.dependencies import _decode_supabase_jwt

    token = jwt.encode(
        {"sub": "user-123", "aud": "authenticated"},
        "the-wrong-secret-key-that-is-definitely-not-it",
        algorithm="HS256",
    )

    with pytest.raises(HTTPException) as exc:
        await _decode_supabase_jwt(token)
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# _decode_supabase_jwt — ES256 (via JWKS)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decode_es256_valid_token(monkeypatch):
    """ES256 path: the decoder fetches the JWK by kid from the JWKS client
    and verifies the EC signature."""
    import app.dependencies as deps

    private_key = ec.generate_private_key(ec.SECP256R1())
    public_numbers = private_key.public_key().public_numbers()

    # Build the JWK the JWKS endpoint would publish for this EC public key.
    import base64

    def _b64u(n: int) -> str:
        raw = n.to_bytes(32, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    kid = "test-es256-kid"
    jwk = {
        "kty": "EC",
        "crv": "P-256",
        "kid": kid,
        "x": _b64u(public_numbers.x),
        "y": _b64u(public_numbers.y),
        "alg": "ES256",
        "use": "sig",
    }

    class _FakeJwks:
        async def get_key(self, requested_kid):
            return jwk if requested_kid == kid else None

    monkeypatch.setattr(deps, "get_jwks_client", lambda: _FakeJwks())

    token = jwt.encode(
        {"sub": "es-user-9", "aud": "authenticated"},
        private_key,
        algorithm="ES256",
        headers={"kid": kid},
    )

    payload = await deps._decode_supabase_jwt(token)
    assert payload["sub"] == "es-user-9"


@pytest.mark.asyncio
async def test_decode_es256_unknown_kid(monkeypatch):
    import app.dependencies as deps

    class _FakeJwks:
        async def get_key(self, requested_kid):
            return None

    monkeypatch.setattr(deps, "get_jwks_client", lambda: _FakeJwks())

    private_key = ec.generate_private_key(ec.SECP256R1())
    token = jwt.encode(
        {"sub": "es-user-9", "aud": "authenticated"},
        private_key,
        algorithm="ES256",
        headers={"kid": "missing-kid"},
    )

    with pytest.raises(HTTPException) as exc:
        await deps._decode_supabase_jwt(token)
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# verify_internal_secret
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_internal_secret_accepts_correct_header(monkeypatch):
    from app.api.v2.core import dependencies as v2_deps

    monkeypatch.setenv("INTERNAL_API_SECRET", "the-internal-secret")
    get_settings.cache_clear()

    # Returns without raising.
    result = await v2_deps.verify_internal_secret(x_internal_secret="the-internal-secret")
    assert result is None


@pytest.mark.asyncio
async def test_verify_internal_secret_rejects_wrong_header(monkeypatch):
    from app.api.v2.core import dependencies as v2_deps

    monkeypatch.setenv("INTERNAL_API_SECRET", "the-internal-secret")
    get_settings.cache_clear()

    with pytest.raises(HTTPException) as exc:
        await v2_deps.verify_internal_secret(x_internal_secret="wrong-secret")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_internal_secret_rejects_empty_header(monkeypatch):
    from app.api.v2.core import dependencies as v2_deps

    monkeypatch.setenv("INTERNAL_API_SECRET", "the-internal-secret")
    get_settings.cache_clear()

    with pytest.raises(HTTPException) as exc:
        await v2_deps.verify_internal_secret(x_internal_secret="")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_internal_secret_rejects_when_secret_unset(monkeypatch):
    """Fail closed: if INTERNAL_API_SECRET is unset, no header can authenticate."""
    from app.api.v2.core import dependencies as v2_deps

    monkeypatch.setenv("INTERNAL_API_SECRET", "")
    get_settings.cache_clear()

    with pytest.raises(HTTPException) as exc:
        await v2_deps.verify_internal_secret(x_internal_secret="")
    assert exc.value.status_code == 401
