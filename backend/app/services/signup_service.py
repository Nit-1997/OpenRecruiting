from app.config import get_settings
from app.services.supabase import get_supabase_admin_client
from app.services.credit_service import provision_default_credits
from app.logging_config import get_logger
from app.utils import parse_iso_datetime


class SignupBlockedError(ValueError):
    """Raised when a user without a profile or valid invite tries to complete
    signup while SIGNUP_INVITE_ONLY is on.

    With the gate on, only existing users (a profiles row) or pre-provisioned
    invitees (an organization_invites row) may complete signup. With it off --
    the default for a self-hosted instance, where the operator owns the
    Supabase project and controls who can authenticate at all -- a new user
    gets their own organization instead.
    """
    pass


logger = get_logger(__name__)


async def complete_user_signup(user_id: str) -> dict:
    supabase = get_supabase_admin_client()

    existing = await supabase.table("profiles") \
        .select("*") \
        .eq("id", user_id) \
        .single() \
        .execute_async()

    if existing.data:
        return {
            "is_new": False,
            "profile": existing.data,
        }

    auth_user = await supabase.get_auth_user(user_id)
    if not auth_user:
        raise ValueError("Auth user not found")

    user_meta = auth_user.get("user_metadata", {})
    email = auth_user.get("email", "")
    full_name = user_meta.get("full_name") or user_meta.get("name") or ""
    avatar_url = user_meta.get("avatar_url") or user_meta.get("picture") or ""

    org_name = f"{full_name}'s Workspace" if full_name else "My Workspace"

    invite = None
    try:
        invite_result = await supabase.table("organization_invites") \
            .select("*, organizations(id, name, org_type)") \
            .eq("email", email) \
            .eq("status", "pending") \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute_async()
    except Exception as e:
        # A DB read failure here is a transient infrastructure issue, not a
        # confirmed "no invite". Re-raise so the API layer returns 500 WITHOUT
        # deleting the orphan auth.users row (preserves legitimate invitees).
        logger.warning(
            "invite_lookup_failed",
            extra={"user_id": user_id, "email": email, "error": str(e)},
        )
        raise

    if invite_result.data:
        inv = invite_result.data[0] if isinstance(invite_result.data, list) else invite_result.data
        try:
            from datetime import datetime, timezone
            expires = parse_iso_datetime(inv["expires_at"])
            if expires > datetime.now(timezone.utc):
                invite = inv
        except Exception as e:
            # Bad data shape on a single invite row is a deterministic rejection,
            # not a transient failure: treat as "no valid invite" and proceed
            # to the gate. Log so we can spot the data quality issue.
            logger.warning(
                "invite_parse_failed",
                extra={"user_id": user_id, "email": email, "error": str(e)},
            )

    if invite:
        target_org_id = invite["organization_id"]

        current_members = await supabase.table("profiles") \
            .select("id") \
            .eq("organization_id", target_org_id) \
            .is_("deleted_at", "null") \
            .count_async()

        sub_result = await supabase.table("subscriptions") \
            .select("custom_max_users, plan_id, plans(max_users)") \
            .eq("organization_id", target_org_id) \
            .eq("status", "active") \
            .limit(1) \
            .execute_async()

        seat_ok = True
        if sub_result.data:
            sub = sub_result.data[0] if isinstance(sub_result.data, list) else sub_result.data
            max_users = sub.get("custom_max_users")
            if max_users is None and sub.get("plans"):
                max_users = sub["plans"].get("max_users")
            if max_users and max_users != -1 and current_members >= max_users:
                seat_ok = False
                logger.warning("invite_seat_limit_reached", extra={
                    "org_id": target_org_id, "current": current_members, "max": max_users,
                })

        if seat_ok:
            await supabase.table("organization_invites") \
                .update({"status": "accepted", "accepted_at": "now()"}) \
                .eq("id", invite["id"]) \
                .execute_async()

            profile_result = await supabase.table("profiles").insert({
                "id": user_id,
                "email": email,
                "full_name": full_name,
                "avatar_url": avatar_url,
                "organization_id": target_org_id,
            }).execute_async()

            org_name_display = invite.get("organizations", {}).get("name", "enterprise org")
            logger.info("signup_via_invite", extra={
                "user_id": user_id, "email": email,
                "org_id": target_org_id, "org_name": org_name_display,
            })

            return {
                "is_new": True,
                "profile": profile_result.data,
                "organization_id": target_org_id,
            }

    if get_settings().SIGNUP_INVITE_ONLY:
        logger.warning("signup_blocked", extra={
            "user_id": user_id,
            "email": email,
            "reason": "no_valid_invite",
        })
        raise SignupBlockedError(
            "Sign-up is invite-only. Please contact your administrator for access."
        )

    # Permissive path (the default for a self-hosted instance): no invite is
    # required, so give the new user their own organization. Who can reach this
    # at all is already controlled by the operator's Supabase auth settings.
    org_result = await supabase.table("organizations").insert({
        "name": org_name,
        "org_type": "team",
    }).execute_async()
    new_org = (
        org_result.data[0] if isinstance(org_result.data, list) else org_result.data
    )
    new_org_id = new_org["id"]

    await provision_default_credits(str(new_org_id))

    profile_result = await supabase.table("profiles").insert({
        "id": user_id,
        "email": email,
        "full_name": full_name,
        "avatar_url": avatar_url,
        "organization_id": new_org_id,
    }).execute_async()

    logger.info("signup_self_serve", extra={
        "user_id": user_id, "email": email, "org_id": new_org_id,
    })

    return {
        "is_new": True,
        "profile": profile_result.data,
        "organization_id": new_org_id,
    }
