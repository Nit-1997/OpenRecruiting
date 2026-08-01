"""Persistence layer for Dynamic Client Registration (RFC 7591).

We register one row per (MCP client × user) — Claude.ai registers a fresh
client_id the first time a user adds the connector. Re-registration with the
same redirect URI is idempotent in v1: we return the existing client.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from app.services.supabase import get_supabase_admin_client


_TABLE = "oauth_clients"
_ALLOWED_GRANTS = {"authorization_code", "refresh_token"}
_ALLOWED_RESPONSES = {"code"}


@dataclass(frozen=True)
class OAuthClient:
    client_id: str
    client_name: str | None
    redirect_uris: list[str]
    grant_types: list[str]
    response_types: list[str]
    token_endpoint_auth_method: str
    scope: str


def _row_to_client(row: dict[str, Any]) -> OAuthClient:
    return OAuthClient(
        client_id=row["client_id"],
        client_name=row.get("client_name"),
        redirect_uris=list(row.get("redirect_uris") or []),
        grant_types=list(row.get("grant_types") or []),
        response_types=list(row.get("response_types") or []),
        token_endpoint_auth_method=row.get("token_endpoint_auth_method") or "none",
        scope=row.get("scope") or "cortex:read",
    )


def _generate_client_id() -> str:
    # RFC 6749 §2.3.1: client_id is opaque, "MUST NOT be guessable". 32 url-safe
    # bytes ≈ 192 bits of entropy. Prefix lets us debug at a glance.
    return f"mcp_{secrets.token_urlsafe(24)}"


async def register_client(
    *,
    client_name: str | None,
    redirect_uris: list[str],
    grant_types: list[str] | None = None,
    response_types: list[str] | None = None,
    token_endpoint_auth_method: str = "none",
    scope: str = "cortex:read",
    software_id: str | None = None,
    software_version: str | None = None,
) -> OAuthClient:
    """Insert a new client_id row. Raises ValueError on invalid metadata.

    Validation:
      - at least one redirect_uri, all https or http://localhost
      - grant_types ⊂ {authorization_code, refresh_token}
      - response_types ⊂ {code}
      - token_endpoint_auth_method ∈ {none, client_secret_basic}
    """
    if not redirect_uris:
        raise ValueError("At least one redirect_uri is required.")
    for uri in redirect_uris:
        if not (uri.startswith("https://") or uri.startswith("http://localhost") or uri.startswith("http://127.0.0.1")):
            raise ValueError(f"redirect_uri must be https:// or http://localhost (got {uri!r})")

    grants = grant_types or ["authorization_code", "refresh_token"]
    bad_grants = set(grants) - _ALLOWED_GRANTS
    if bad_grants:
        raise ValueError(f"Unsupported grant_types: {sorted(bad_grants)}")

    responses = response_types or ["code"]
    bad_responses = set(responses) - _ALLOWED_RESPONSES
    if bad_responses:
        raise ValueError(f"Unsupported response_types: {sorted(bad_responses)}")

    if token_endpoint_auth_method not in {"none", "client_secret_basic"}:
        raise ValueError(
            f"Unsupported token_endpoint_auth_method: {token_endpoint_auth_method!r}. "
            f"This authorization server only supports public clients (PKCE)."
        )

    client_id = _generate_client_id()
    supabase = get_supabase_admin_client()
    row = {
        "client_id": client_id,
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "grant_types": grants,
        "response_types": responses,
        "token_endpoint_auth_method": token_endpoint_auth_method,
        "scope": scope,
        "software_id": software_id,
        "software_version": software_version,
    }
    await supabase.table(_TABLE).insert(row).execute_async()
    return _row_to_client(row)


async def get_client(client_id: str) -> OAuthClient | None:
    supabase = get_supabase_admin_client()
    result = (
        await supabase.table(_TABLE)
        .select("*")
        .eq("client_id", client_id)
        .single()
        .execute_async()
    )
    if not result.data:
        return None
    return _row_to_client(result.data)


def validate_redirect_uri(client: OAuthClient, redirect_uri: str) -> bool:
    """RFC 6749 §3.1.2: redirect_uri must be an exact match against the
    registered values. No wildcards, no prefix-matching."""
    return redirect_uri in client.redirect_uris
