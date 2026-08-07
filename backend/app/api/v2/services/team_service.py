"""
Team service for v2.

Single source of truth for teammate invites. `POST /api/v2/team/invite`
(recruiter, authed) calls `invite_teammate`.

Keeping one implementation here means duplicate handling, seat enforcement,
the 7-day expiry, the Supabase invite-email + phantom-profile creation, and the
invite-row insert stay in one place. The router layer maps the returned invite
row to its own response shape and maps the raised domain errors
(ConflictError/ForbiddenError) to HTTP via the app-wide v2 error handlers.
"""

from app.api.v2.core.exceptions import ConflictError, ForbiddenError
from app.config import get_settings
from app.logging_config import get_logger
from app.services.supabase import SupabaseAdminClient

logger = get_logger(__name__)


async def _get_seat_limit(supabase: SupabaseAdminClient, org_id: str) -> int:
    sub = await supabase.table("subscriptions") \
        .select("custom_max_users, plans(max_users)") \
        .eq("organization_id", org_id) \
        .eq("status", "active") \
        .limit(1) \
        .execute_async()
    if not sub.data:
        return 1
    row = sub.data[0] if isinstance(sub.data, list) else sub.data
    limit = row.get("custom_max_users")
    if limit is None and row.get("plans"):
        limit = row["plans"].get("max_users")
    return limit if limit is not None else 1


async def invite_teammate(
    supabase: SupabaseAdminClient,
    *,
    org_id: str,
    invited_by_profile_id: str,
    email: str,
) -> dict:
    """Invite a teammate by email; return the created `organization_invites` row.

    Raises:
        ConflictError: duplicate member / pending invite / existing OpenRecruiting
            account, or the invite-email send failed (EMAIL_FAILED — static
            message, the raw provider error is logged server-side only).
        ForbiddenError: the org's seat limit is reached.
    """
    email = email.lower()

    existing_member = await supabase.table("profiles") \
        .select("id") \
        .eq("organization_id", org_id) \
        .eq("email", email) \
        .is_("deleted_at", "null") \
        .eq("onboarding_completed", True) \
        .execute_async()
    if existing_member.data:
        raise ConflictError("ALREADY_MEMBER", f"{email} is already a member of your organization")

    existing_invite = await supabase.table("organization_invites") \
        .select("id") \
        .eq("organization_id", org_id) \
        .eq("email", email) \
        .eq("status", "pending") \
        .execute_async()
    if existing_invite.data:
        raise ConflictError("INVITE_EXISTS", f"An invite has already been sent to {email}")

    seat_limit = await _get_seat_limit(supabase, org_id)
    if seat_limit != -1:
        members_result = await supabase.table("profiles") \
            .select("id") \
            .eq("organization_id", org_id) \
            .is_("deleted_at", "null") \
            .execute_async()
        pending_result = await supabase.table("organization_invites") \
            .select("id") \
            .eq("organization_id", org_id) \
            .eq("status", "pending") \
            .execute_async()
        if len(members_result.data or []) + len(pending_result.data or []) >= seat_limit:
            raise ForbiddenError(f"Seat limit reached ({seat_limit}). Contact support to increase.")

    settings = get_settings()

    existing_profile = await supabase.table("profiles") \
        .select("id") \
        .eq("email", email) \
        .is_("deleted_at", "null") \
        .execute_async()
    if existing_profile.data:
        raise ConflictError("EXISTING_USER", f"{email} already has a OpenRecruiting account and cannot be invited.")

    try:
        auth_result = await supabase.invite_user_by_email(
            email,
            redirect_to=f"{settings.APP_URL}/set-password",
        )
        auth_user_id = auth_result.get("id") if isinstance(auth_result, dict) else None
        if auth_user_id:
            await supabase.table("profiles").insert({
                "id": auth_user_id,
                "organization_id": org_id,
                "email": email,
                "is_staff": False,
                "invitation_status": "invited",
                "onboarding_completed": False,
            }).execute_async()
    except ConflictError:
        raise
    except Exception as e:
        # Log the raw provider error server-side; surface a STATIC message so
        # internal infrastructure detail (keys, hosts, gotrue internals) never
        # leaks to the client.
        logger.error(
            "team_invite_email_failed",
            extra={"org_id": org_id, "email": email, "error": str(e)},
        )
        raise ConflictError("EMAIL_FAILED", "Failed to send the invitation email. Please try again.")

    result = await supabase.table("organization_invites").insert({
        "organization_id": org_id,
        "email": email,
        "invited_by": invited_by_profile_id,
    }).execute_async()

    row = result.data[0] if isinstance(result.data, list) else result.data
    logger.info(
        "team_invite_sent",
        extra={"org_id": org_id, "email": email, "invited_by": invited_by_profile_id},
    )
    return row
