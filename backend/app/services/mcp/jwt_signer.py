"""RS256 JWT signing for MCP access tokens.

We use a long-lived RSA keypair shared across all MCP resource servers
(Cortex MCP, future OpenRecruiting MCPs). The private key is held only by backend
(this process). Resource servers verify tokens against the public key exposed
at /.well-known/jwks.json.

Key material is loaded from environment variables:
  MCP_JWT_PRIVATE_KEY_PEM    PKCS#8 PEM-encoded RSA private key
  MCP_JWT_KEY_ID             Stable kid identifier (so we can rotate later)
  MCP_JWT_ISSUER             iss claim, e.g. "http://localhost:8004"

Rotation strategy (deferred to v2): introduce MCP_JWT_PRIVATE_KEY_PEM_NEXT
alongside the existing one, expose both public keys in JWKS for the overlap
window, and have the signer switch over after refresh tokens drain.
"""
from __future__ import annotations

import base64
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from app.config import get_settings


@dataclass(frozen=True)
class SignedToken:
    token: str
    expires_in: int   # seconds
    issued_at: int    # unix seconds
    kid: str
    audience: str


def _int_to_b64url(n: int) -> str:
    byte_length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(byte_length, "big")).rstrip(b"=").decode("ascii")


@lru_cache(maxsize=1)
def _load_private_key() -> RSAPrivateKey:
    settings = get_settings()
    # `.env` carries the PEM on a single line with \n escapes, because compose's
    # env_file cannot express a multi-line value -- so decode them back before
    # parsing. A PEM that already has real newlines contains no literal "\n"
    # sequence, which makes this a no-op for that form.
    pem = (settings.MCP_JWT_PRIVATE_KEY_PEM or "").replace("\\n", "\n").encode("utf-8")
    if not pem.strip():
        raise RuntimeError(
            "MCP_JWT_PRIVATE_KEY_PEM is not configured. Generate an RSA "
            "keypair (RS256) and set the PEM-encoded private key in the env."
        )
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, RSAPrivateKey):
        raise RuntimeError("MCP_JWT_PRIVATE_KEY_PEM must be an RSA private key.")
    return key


@lru_cache(maxsize=1)
def _public_key() -> RSAPublicKey:
    return _load_private_key().public_key()


def _kid() -> str:
    settings = get_settings()
    return settings.MCP_JWT_KEY_ID or "mcp-key-1"


def _issuer() -> str:
    settings = get_settings()
    return settings.MCP_JWT_ISSUER or "http://localhost:8004"


def sign_access_token(
    *,
    subject: str,
    audience: str,
    org_id: str,
    org_name: str,
    user_name: str | None,
    role: str | None,
    scope: str,
    ttl_seconds: int = 3600,
    extra_claims: dict[str, Any] | None = None,
) -> SignedToken:
    """Mint a signed RS256 JWT for the MCP resource server identified by `audience`.

    Resource servers (Cortex MCP, etc.) verify with the public JWKS and check:
      iss == MCP_JWT_ISSUER
      aud == their configured audience string
      exp in the future
      scope contains the scope they require (e.g. "cortex:read")
    """
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": _issuer(),
        "sub": subject,
        "aud": audience,
        "iat": now,
        "exp": now + ttl_seconds,
        "jti": uuid.uuid4().hex,
        "scope": scope,
        "org_id": org_id,
        "org_name": org_name,
    }
    if user_name:
        claims["name"] = user_name
    if role:
        claims["role"] = role
    if extra_claims:
        # Never let extras override security-critical claims.
        for forbidden in ("iss", "sub", "aud", "iat", "exp", "scope", "org_id", "jti"):
            extra_claims.pop(forbidden, None)
        claims.update(extra_claims)

    pem = _load_private_key().private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    token = jwt.encode(claims, pem, algorithm="RS256", headers={"kid": _kid()})
    return SignedToken(
        token=token,
        expires_in=ttl_seconds,
        issued_at=now,
        kid=_kid(),
        audience=audience,
    )


def public_jwks() -> dict[str, Any]:
    """Return the JSON Web Key Set with the current signing key's public half."""
    public_numbers = _public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": _kid(),
                "n": _int_to_b64url(public_numbers.n),
                "e": _int_to_b64url(public_numbers.e),
            }
        ]
    }


def reset_key_cache() -> None:
    """Clear cached key state — only used by tests to rotate the keypair."""
    _load_private_key.cache_clear()
    _public_key.cache_clear()
