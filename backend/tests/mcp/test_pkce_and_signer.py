"""Unit tests for the PKCE helper and JWT signer."""
from __future__ import annotations

import base64
import hashlib

import pytest
import jwt as jose_jwt

from app.services.mcp import pkce
from app.services.mcp.jwt_signer import (
    public_jwks,
    sign_access_token,
)


def _make_verifier_challenge(length: int = 64) -> tuple[str, str]:
    import secrets
    verifier = secrets.token_urlsafe(96)[:length]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class TestPKCE:
    def test_s256_matching_pair_passes(self):
        v, c = _make_verifier_challenge()
        pkce.verify(v, c, "S256")  # does not raise

    def test_mismatched_pair_fails(self):
        v, _ = _make_verifier_challenge()
        with pytest.raises(pkce.PKCEError):
            pkce.verify(v, "tampered-challenge-value", "S256")

    def test_plain_method_rejected(self):
        with pytest.raises(pkce.PKCEError, match="S256"):
            pkce.verify("x" * 50, "x" * 50, "plain")

    def test_short_verifier_rejected(self):
        with pytest.raises(pkce.PKCEError, match="length"):
            pkce.verify("short", "x" * 43, "S256")

    def test_long_verifier_rejected(self):
        with pytest.raises(pkce.PKCEError, match="length"):
            pkce.verify("x" * 129, "x" * 43, "S256")


class TestSigner:
    def test_token_round_trips_through_jwks(self):
        signed = sign_access_token(
            subject="user-1",
            audience="cortex-mcp",
            org_id="org-1",
            org_name="Acme",
            user_name="Test",
            role="admin",
            scope="cortex:read",
            ttl_seconds=600,
        )
        assert signed.audience == "cortex-mcp"
        assert signed.expires_in == 600

        # Resource-server style verification
        import json
        from jwt.algorithms import RSAAlgorithm
        jwks = public_jwks()
        key = next(k for k in jwks["keys"] if k["kid"] == signed.kid)
        pub = RSAAlgorithm.from_jwk(json.dumps(key))
        claims = jose_jwt.decode(
            signed.token, pub,
            algorithms=["RS256"],
            audience="cortex-mcp",
            issuer="http://testserver",
        )
        assert claims["org_id"] == "org-1"
        assert claims["scope"] == "cortex:read"
        assert claims["org_name"] == "Acme"

    def test_extra_claims_cannot_override_security_fields(self):
        signed = sign_access_token(
            subject="user-1", audience="cortex-mcp",
            org_id="org-1", org_name="Acme",
            user_name=None, role=None,
            scope="cortex:read",
            extra_claims={"sub": "imposter", "org_id": "other", "aud": "other-server"},
        )
        # Decode without aud check to peek at raw claims
        claims = jose_jwt.decode(signed.token, options={"verify_signature": False})
        assert claims["sub"] == "user-1"
        assert claims["org_id"] == "org-1"
        assert claims["aud"] == "cortex-mcp"
