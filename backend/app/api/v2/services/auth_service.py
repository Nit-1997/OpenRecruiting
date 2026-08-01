"""
Auth service for v2.

Endpoints owned:
  GET  /api/v2/auth/me       → get_me (profile + org join)

The frontend authenticates directly against Supabase via `@supabase/supabase-js`
and sends the resulting bearer token on subsequent requests. v2's backend role
is to verify that JWT (see `app/dependencies.py::get_current_user`) and expose
this small helper for joining additional profile data.
"""

from typing import Optional

from app.dependencies import CurrentUser
from app.logging_config import get_logger
from app.services.supabase import SupabaseAdminClient

logger = get_logger(__name__)


async def get_me(
    supabase: SupabaseAdminClient, user: CurrentUser
) -> dict:
    """Return the authenticated user's profile, joined with name from profiles.

    Returns a dict matching MeResponse. The `name` field is the `full_name`
    column on `profiles`. If no profile row exists (shouldn't happen — JWT
    verification in `get_current_user` already enforces a profile lookup),
    fall back to the JWT-derived fields with name=None.
    """
    result = await (
        supabase.table("profiles")
        .select("full_name")
        .eq("id", str(user.id))
        .limit(1)
        .execute_async()
    )
    name: Optional[str] = None
    if result.data:
        row = result.data[0] if isinstance(result.data, list) else result.data
        name = row.get("full_name")

    # Query organization_invites directly — a DB trigger overwrites invitation_status
    # to 'signed_up' on OTP confirmation, making it unreliable as a pending-invite signal.
    invite_result = await (
        supabase.table("organization_invites")
        .select("id")
        .eq("organization_id", str(user.organization_id))
        .eq("email", user.email)
        .eq("status", "pending")
        .limit(1)
        .execute_async()
    ) if user.organization_id else None
    has_pending_invite = bool(invite_result and invite_result.data)

    return {
        "id": user.id,
        "email": user.email,
        "organization_id": user.organization_id,
        "is_staff": user.is_staff,
        "name": name,
        "has_pending_invite": has_pending_invite,
    }
