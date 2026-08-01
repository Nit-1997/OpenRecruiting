"""
Team management routes for v2.

Mounted under /api/v2/team:
  GET    /                      Members, pending invites, seat usage
  POST   /invite                Invite a teammate by email
  POST   /accept-invite         Accept a pending invite (called on first login)
  DELETE /invites/{invite_id}   Cancel a pending invite
  DELETE /members/{user_id}     Remove a member from the org
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
)
from app.api.v2.core.exceptions import ForbiddenError, NotFoundError
from app.api.v2.services import team_service
from app.dependencies import invalidate_profile_cache
from app.logging_config import get_logger
from app.services.supabase import get_supabase_admin_client

logger = get_logger(__name__)

router = APIRouter(prefix="/team", tags=["v2/team"])

_AVATAR_COLORS = [
    "#E8D5FF", "#D5E8FF", "#D5FFE8", "#FFE8D5", "#FFD5E8",
    "#E8FFD5", "#D5FFFF", "#FFD5FF", "#FFFFD5", "#D5D5FF",
]


def _avatar_color(user_id: str) -> str:
    return _AVATAR_COLORS[sum(ord(c) for c in user_id) % len(_AVATAR_COLORS)]


def _avatar_initials(name: str | None, email: str) -> str:
    if name and name.strip():
        parts = name.strip().split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return parts[0][:2].upper()
    return email[:2].upper()


class TeamMemberOut(BaseModel):
    id: str
    user_id: str
    name: str
    email: str
    role: str
    avatar_initials: str
    avatar_color: str
    joined_at: str
    last_active_at: Optional[str] = None


class InviteOut(BaseModel):
    id: str
    email: str
    role: str
    invited_by_id: Optional[str] = None
    invited_by_name: Optional[str] = None
    created_at: str
    expires_at: str
    status: str


class TeamOverviewOut(BaseModel):
    organization_id: str
    organization_name: str
    members: list[TeamMemberOut]
    pending_invites: list[InviteOut]
    seat_usage: dict


class InviteRequest(BaseModel):
    email: EmailStr
    role: str = "recruiter"


async def _get_seat_limit(org_id: str) -> int:
    supabase = get_supabase_admin_client()
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


@router.get("", response_model=TeamOverviewOut)
async def get_team(
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
) -> TeamOverviewOut:
    supabase = get_supabase_admin_client()
    org_id = current.organization_id_str

    org_result = await supabase.table("organizations") \
        .select("name") \
        .eq("id", org_id) \
        .limit(1) \
        .execute_async()
    org_name = (org_result.data[0].get("name", "") if org_result.data else "")

    # onboarding_completed=True for all real members; False for phantom profiles not yet accepted.
    # Positive boolean avoids PostgreSQL's NULL != 'value' = NULL (falsy) behaviour.
    members_result = await supabase.table("profiles") \
        .select("id, email, full_name, created_at") \
        .eq("organization_id", org_id) \
        .is_("deleted_at", "null") \
        .eq("onboarding_completed", True) \
        .order("created_at") \
        .execute_async()

    invites_result = await supabase.table("organization_invites") \
        .select("id, email, invited_by, status, created_at, expires_at") \
        .eq("organization_id", org_id) \
        .eq("status", "pending") \
        .order("created_at", desc=True) \
        .execute_async()

    raw_members = members_result.data or []
    raw_invites = invites_result.data or []
    seat_limit = await _get_seat_limit(org_id)

    owner_id = raw_members[0]["id"] if raw_members else None
    members = [
        TeamMemberOut(
            id=m["id"],
            user_id=m["id"],
            name=m.get("full_name") or "",
            email=m.get("email") or "",
            role="owner" if m["id"] == owner_id else "recruiter",
            avatar_initials=_avatar_initials(m.get("full_name"), m.get("email") or ""),
            avatar_color=_avatar_color(m["id"]),
            joined_at=m.get("created_at") or "",
            last_active_at=None,
        )
        for m in raw_members
    ]

    inviter_ids = list({i["invited_by"] for i in raw_invites if i.get("invited_by")})
    inviter_map: dict[str, str] = {}
    if inviter_ids:
        inviter_result = await supabase.table("profiles") \
            .select("id, full_name, email") \
            .in_("id", inviter_ids) \
            .execute_async()
        for p in (inviter_result.data or []):
            inviter_map[p["id"]] = p.get("full_name") or p.get("email") or ""

    default_expires = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    invites = [
        InviteOut(
            id=i["id"],
            email=i["email"],
            role="recruiter",
            invited_by_id=i.get("invited_by"),
            invited_by_name=inviter_map.get(i.get("invited_by") or ""),
            created_at=i.get("created_at") or "",
            expires_at=i.get("expires_at") or default_expires,
            status=i.get("status") or "pending",
        )
        for i in raw_invites
    ]

    return TeamOverviewOut(
        organization_id=org_id,
        organization_name=org_name,
        members=members,
        pending_invites=invites,
        seat_usage={"used": len(members), "total": seat_limit},
    )


@router.post("/invite", response_model=InviteOut)
async def invite_teammate(
    req: InviteRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
) -> InviteOut:
    supabase = get_supabase_admin_client()
    row = await team_service.invite_teammate(
        supabase,
        org_id=current.organization_id_str,
        invited_by_profile_id=str(current.user.id),
        email=req.email,
    )
    return InviteOut(
        id=row["id"],
        email=row["email"],
        role="recruiter",
        invited_by_id=str(current.user.id),
        invited_by_name=None,
        created_at=row.get("created_at") or "",
        expires_at=row.get("expires_at") or (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(),
        status=row.get("status") or "pending",
    )


@router.post("/accept-invite")
async def accept_invite(
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
) -> dict:
    supabase = get_supabase_admin_client()
    org_id = current.organization_id_str
    email = current.user.email

    invite = await supabase.table("organization_invites") \
        .select("id") \
        .eq("organization_id", org_id) \
        .eq("email", email) \
        .eq("status", "pending") \
        .limit(1) \
        .execute_async()

    if not invite.data:
        return {"status": "ok"}

    now = datetime.now(timezone.utc).isoformat()
    await supabase.table("organization_invites") \
        .update({"status": "accepted", "accepted_at": now}) \
        .eq("id", invite.data[0]["id"]) \
        .execute_async()

    await supabase.table("profiles") \
        .update({"invitation_status": None, "onboarding_completed": True}) \
        .eq("id", str(current.user.id)) \
        .execute_async()

    invalidate_profile_cache(str(current.user.id))
    logger.info(f"team_invite_accepted: org={org_id} email={email}")
    return {"status": "ok"}


@router.delete("/invites/{invite_id}")
async def cancel_invite(
    invite_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
) -> dict:
    supabase = get_supabase_admin_client()
    org_id = current.organization_id_str

    invite_result = await supabase.table("organization_invites") \
        .select("id, email, organization_id") \
        .eq("id", str(invite_id)) \
        .eq("status", "pending") \
        .limit(1) \
        .execute_async()

    if not invite_result.data:
        raise NotFoundError("Invite not found or already cancelled")
    invite = invite_result.data[0]
    if invite["organization_id"] != org_id:
        raise ForbiddenError("Not authorized to cancel this invite")

    # Unique constraint on (organization_id, email, status): remove any prior cancelled
    # record before updating the current one, keeping only the most recent cancellation.
    existing_cancelled = await supabase.table("organization_invites") \
        .select("id") \
        .eq("organization_id", org_id) \
        .eq("email", invite["email"]) \
        .eq("status", "cancelled") \
        .limit(1) \
        .execute_async()

    if existing_cancelled.data:
        await supabase.table("organization_invites") \
            .delete() \
            .eq("id", existing_cancelled.data[0]["id"]) \
            .execute_async()

    await supabase.table("organization_invites") \
        .update({"status": "cancelled"}) \
        .eq("id", str(invite["id"])) \
        .execute_async()

    # Delete phantom profile and auth user if the invite was never accepted,
    # so the email can be cleanly re-invited.
    phantom = await supabase.table("profiles") \
        .select("id") \
        .eq("email", invite["email"]) \
        .eq("onboarding_completed", False) \
        .limit(1) \
        .execute_async()

    if phantom.data:
        phantom_id = phantom.data[0]["id"]
        await supabase.table("profiles").delete().eq("id", phantom_id).execute_async()
        try:
            await supabase.delete_user(phantom_id)
        except Exception as e:
            logger.warning(f"team_cancel_invite_auth_cleanup_failed: user={phantom_id} error={e}")

    return {"status": "ok", "message": "Invite cancelled"}


@router.delete("/members/{user_id}")
async def remove_member(
    user_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
) -> dict:
    supabase = get_supabase_admin_client()
    org_id = current.organization_id_str

    if str(user_id) == str(current.user.id):
        raise ForbiddenError("You cannot remove yourself from the organization")

    member_result = await supabase.table("profiles") \
        .select("id, full_name, organization_id") \
        .eq("id", str(user_id)) \
        .eq("organization_id", org_id) \
        .is_("deleted_at", "null") \
        .limit(1) \
        .execute_async()

    if not member_result.data:
        raise NotFoundError("Member not found in your organization")
    member = member_result.data[0]

    first_member = await supabase.table("profiles") \
        .select("id") \
        .eq("organization_id", org_id) \
        .is_("deleted_at", "null") \
        .eq("onboarding_completed", True) \
        .order("created_at") \
        .limit(1) \
        .execute_async()

    if first_member.data and first_member.data[0]["id"] == str(user_id):
        raise ForbiddenError("Cannot remove the organization owner")

    full_name = member.get("full_name") or ""
    new_org_name = f"{full_name}'s Workspace" if full_name else "My Workspace"

    new_org = await supabase.table("organizations").insert({
        "name": new_org_name,
        "org_type": "personal",
    }).execute_async()

    new_org_id = new_org.data[0]["id"] if isinstance(new_org.data, list) else new_org.data["id"]

    await supabase.table("profiles") \
        .update({"organization_id": new_org_id}) \
        .eq("id", str(user_id)) \
        .execute_async()

    logger.info(f"team_member_removed: org={org_id} user={user_id} new_org={new_org_id}")

    return {"status": "ok", "message": "Member removed and moved to personal workspace"}
