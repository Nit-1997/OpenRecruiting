"""Refresh token persistence.

Refresh tokens are long-lived (30 days). We store only the SHA-256 hash so
a database leak cannot be replayed against the token endpoint.

Rotation: on every successful refresh, we mark the old token revoked and
issue a brand-new one (a la RFC 6749 §6 / OAuth 2.1). Old refresh tokens
become useless immediately after use.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.supabase import get_supabase_admin_client


_TABLE = "oauth_refresh_tokens"
DEFAULT_TTL_SECONDS = 30 * 24 * 3600  # 30 days


@dataclass(frozen=True)
class RefreshToken:
    token: str           # plaintext — return to caller, not stored
    token_hash: str
    client_id: str
    user_id: str
    organization_id: str | None
    scope: str
    audience: str
    expires_at: datetime


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def issue_refresh_token(
    *,
    client_id: str,
    user_id: str,
    organization_id: str | None,
    scope: str,
    audience: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> RefreshToken:
    token = secrets.token_urlsafe(48)
    token_hash = _hash(token)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    row = {
        "token_hash": token_hash,
        "client_id": client_id,
        "user_id": user_id,
        "organization_id": organization_id,
        "scope": scope,
        "audience": audience,
        "revoked": False,
        "expires_at": expires_at.isoformat(),
    }
    supabase = get_supabase_admin_client()
    await supabase.table(_TABLE).insert(row).execute_async()
    return RefreshToken(
        token=token,
        token_hash=token_hash,
        client_id=client_id,
        user_id=user_id,
        organization_id=organization_id,
        scope=scope,
        audience=audience,
        expires_at=expires_at,
    )


async def use_refresh_token(token: str, *, client_id: str) -> RefreshToken | None:
    """Atomically rotate a refresh token: revoke the presented one and
    return its record so the caller can mint a fresh access+refresh pair.

    Implemented as a single conditional UPDATE filtered on `token_hash`,
    `client_id`, `revoked=false`, and `expires_at > now()`, returning the
    row that was actually flipped. Concurrent refreshes that race on the
    same token serialize on the row lock — exactly one transaction sees
    `revoked=false` and rotates; every other refresh gets None. Without
    this, two concurrent refreshes would both observe `revoked=false`,
    both revoke the old row, and both mint new tokens, leaving multiple
    valid token branches.

    Returns None on any failure: unknown hash, revoked, expired, or bound
    to a different client_id.
    """
    token_hash = _hash(token)
    now = datetime.now(timezone.utc)
    supabase = get_supabase_admin_client()
    result = await (
        supabase.table(_TABLE)
        .update({"revoked": True, "last_used_at": now.isoformat()})
        .eq("token_hash", token_hash)
        .eq("client_id", client_id)
        .eq("revoked", False)
        .gt("expires_at", now.isoformat())
        .execute_async()
    )
    if not result.data:
        return None
    row: dict[str, Any] = result.data if isinstance(result.data, dict) else result.data[0]

    return RefreshToken(
        token=token,
        token_hash=token_hash,
        client_id=row["client_id"],
        user_id=row["user_id"],
        organization_id=row.get("organization_id"),
        scope=row["scope"],
        audience=row["audience"],
        expires_at=_parse_ts(row["expires_at"]),
    )


async def revoke_refresh_token(token: str) -> bool:
    """Mark a refresh token revoked. Idempotent; returns True iff a row was changed."""
    token_hash = _hash(token)
    supabase = get_supabase_admin_client()
    result = (
        await supabase.table(_TABLE)
        .update({"revoked": True})
        .eq("token_hash", token_hash)
        .eq("revoked", False)
        .execute_async()
    )
    return bool(result.data)


def _parse_ts(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)
