"""Short-lived authorization-code persistence.

Codes are minted by /authorize after user consent and exchanged once at
/token. They expire in 5 minutes (RFC 6749 §10.5 recommends ≤ 10 min) and
are marked consumed on first use to prevent replay.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.supabase import get_supabase_admin_client


_TABLE = "oauth_authorization_codes"
_CODE_TTL_SECONDS = 300


@dataclass(frozen=True)
class AuthorizationCode:
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


def _generate_code() -> str:
    return secrets.token_urlsafe(32)


async def issue_code(
    *,
    client_id: str,
    user_id: str,
    organization_id: str | None,
    redirect_uri: str,
    scope: str,
    audience: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
) -> AuthorizationCode:
    code = _generate_code()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=_CODE_TTL_SECONDS)
    row = {
        "code": code,
        "client_id": client_id,
        "user_id": user_id,
        "organization_id": organization_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "audience": audience,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "consumed": False,
        "expires_at": expires_at.isoformat(),
    }
    supabase = get_supabase_admin_client()
    await supabase.table(_TABLE).insert(row).execute_async()
    return AuthorizationCode(
        code=code,
        client_id=client_id,
        user_id=user_id,
        organization_id=organization_id,
        redirect_uri=redirect_uri,
        scope=scope,
        audience=audience,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        consumed=False,
        expires_at=expires_at,
    )


async def consume_code(code: str) -> AuthorizationCode | None:
    """Atomically consume an authorization code, returning the row iff this
    call is the one that flipped it from unconsumed → consumed.

    Implemented as a single conditional `UPDATE ... WHERE code=$1 AND
    consumed=false AND expires_at > now() RETURNING *`. Postgres serializes
    UPDATEs on the same row, so under concurrent `/token` exchanges only the
    first transaction observes `consumed=false` — every subsequent caller
    matches zero rows and gets None. Replay and double-spend both fail.

    Returns None if the code is unknown, already consumed, or expired.
    """
    supabase = get_supabase_admin_client()
    now_iso = datetime.now(timezone.utc).isoformat()
    result = await (
        supabase.table(_TABLE)
        .update({"consumed": True})
        .eq("code", code)
        .eq("consumed", False)
        .gt("expires_at", now_iso)
        .execute_async()
    )
    # PostgREST returns the updated rows under `Prefer: return=representation`.
    # The shim collapses a single-row list into the row dict; an empty list
    # (no row matched the predicates) stays a list and is falsy.
    if not result.data:
        return None
    row: dict[str, Any] = result.data if isinstance(result.data, dict) else result.data[0]

    return AuthorizationCode(
        code=row["code"],
        client_id=row["client_id"],
        user_id=row["user_id"],
        organization_id=row.get("organization_id"),
        redirect_uri=row["redirect_uri"],
        scope=row["scope"],
        audience=row["audience"],
        code_challenge=row["code_challenge"],
        code_challenge_method=row.get("code_challenge_method") or "S256",
        consumed=True,
        expires_at=_parse_ts(row["expires_at"]),
    )


def _parse_ts(value: str) -> datetime:
    # Supabase returns timestamps as ISO 8601 with timezone info.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)
