"""Validate Scout-issued JWTs and extract auth context.

The token issuer is `backend`. Required claims:
  sub        — user_id
  org_id     — organization UUID, used as the Neo4j group_id binding
  org_name   — display name (for who_am_i)
  scope      — space-delimited; must include "cortex:read"
  aud        — must equal settings.oidc_audience
  iss        — must equal settings.oidc_issuer
  exp        — standard expiry
"""
from __future__ import annotations

import time
from functools import lru_cache
from typing import Any

import httpx
import structlog
from jose import jwt
from jose.exceptions import JWTError

from src.auth.context import AuthContext
from src.config.settings import get_settings

logger = structlog.get_logger(__name__)


class AuthError(Exception):
    """Raised when token validation fails. Surfaces as 401 to the MCP client."""


_JWKS_CACHE: dict[str, Any] = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL_SECONDS = 600


async def _fetch_jwks() -> dict[str, Any]:
    settings = get_settings()
    now = time.time()
    if _JWKS_CACHE["keys"] is not None and now - _JWKS_CACHE["fetched_at"] < _JWKS_TTL_SECONDS:
        return _JWKS_CACHE["keys"]

    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(settings.oidc_jwks_url)
        resp.raise_for_status()
        jwks = resp.json()

    _JWKS_CACHE["keys"] = jwks
    _JWKS_CACHE["fetched_at"] = now
    return jwks


async def validate_token(token: str) -> AuthContext:
    """Validate a bearer JWT and return an AuthContext. Raises AuthError on failure."""
    settings = get_settings()
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise AuthError(f"Malformed token header: {e}") from e

    kid = unverified_header.get("kid")
    if not kid:
        raise AuthError("Token missing kid header")

    jwks = await _fetch_jwks()
    key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if key is None:
        raise AuthError(f"No matching key for kid={kid}")

    # Accept any audience in the comma-separated allowlist. The MCP/OAuth
    # spec uses RFC 8707 Resource Indicators — Claude Desktop sends the
    # cortex-mcp URL as the resource, which becomes the `aud` claim. We
    # also accept the short canonical form so dev tokens
    # (mint_dev_token.py) keep working without knowing the deployment URL.
    #
    # python-jose's jwt.decode requires `audience` to be a single string,
    # not a list. So we skip its built-in audience check and verify the
    # `aud` claim ourselves below.
    allowed_auds = {
        a.strip().rstrip("/")
        for a in settings.oidc_audience.split(",")
        if a.strip()
    }
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[key.get("alg", "RS256")],
            issuer=settings.oidc_issuer,
            options={"verify_aud": False},
        )
    except JWTError as e:
        raise AuthError(f"Token verification failed: {e}") from e

    token_aud = claims.get("aud")
    token_auds = (
        [token_aud] if isinstance(token_aud, str)
        else list(token_aud) if isinstance(token_aud, (list, tuple))
        else []
    )
    normalized = {a.rstrip("/") for a in token_auds if isinstance(a, str)}
    if not normalized & allowed_auds:
        raise AuthError(
            f"Token verification failed: audience {token_aud!r} is not in "
            f"the allowed set {sorted(allowed_auds)}"
        )

    return _claims_to_context(claims)


def _claims_to_context(claims: dict[str, Any]) -> AuthContext:
    user_id = claims.get("sub")
    org_id = claims.get("org_id")
    if not user_id or not org_id:
        raise AuthError("Token missing required claims (sub, org_id)")

    scope_str = claims.get("scope", "")
    scopes = tuple(scope_str.split()) if isinstance(scope_str, str) else tuple(scope_str)

    if "cortex:read" not in scopes:
        raise AuthError("Token lacks cortex:read scope")

    return AuthContext(
        user_id=user_id,
        org_id=org_id,
        org_name=claims.get("org_name") or "",
        user_name=claims.get("name"),
        role=claims.get("role"),
        scopes=scopes,
    )
