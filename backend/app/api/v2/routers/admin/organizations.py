from fastapi import APIRouter, Depends, HTTPException, status, Query
from uuid import UUID
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone
import asyncio
from app.logging_config import get_logger
from app.dependencies import require_staff, CurrentUser, invalidate_profile_cache
from app.models.organization import (
    OrganizationCreate,
    OrganizationResponse,
    OrganizationListResponse
)
from app.services.supabase import get_supabase_admin_client
from app.services.credit_service import provision_default_credits, set_org_budget
from app.api.v2.core.rpc import call_rpc

logger = get_logger(__name__)


class DeleteOrganizationResponse(BaseModel):
    message: str
    organization_id: UUID


class OrgCreditsUpdate(BaseModel):
    """-1 means unlimited. Omitted fields are left untouched."""
    intake_total: Optional[int] = Field(default=None, ge=-1)
    interview_total: Optional[int] = Field(default=None, ge=-1)


class MigrateUserRequest(BaseModel):
    user_id: UUID


router = APIRouter(prefix="/organizations", tags=["Organizations"])


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_organization(
    org: OrganizationCreate,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    data = {
        "name": org.name,
        "domain": org.domain,
    }

    result = await supabase.table("organizations").insert(data).execute_async()

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create organization"
        )

    row = result.data[0] if isinstance(result.data, list) else result.data
    await provision_default_credits(str(row["id"]))

    return result.data


@router.get("", response_model=OrganizationListResponse)
async def list_organizations(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: CurrentUser = Depends(require_staff),
):
    supabase = get_supabase_admin_client()
    offset = (page - 1) * page_size
    result, total = await asyncio.gather(
        supabase.table("organizations").select("*").is_null("deleted_at").order("created_at", desc=True).limit(page_size).offset(offset).execute_async(),
        supabase.table("organizations").select("id").is_null("deleted_at").count_async(),
    )
    organizations = result.data if isinstance(result.data, list) else [result.data] if result.data else []
    return OrganizationListResponse(organizations=organizations, total=total)


@router.get("/archived", response_model=OrganizationListResponse)
async def list_archived_organizations(
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()
    result = await supabase.table("organizations").select("*").not_null("deleted_at").execute_async()

    organizations = result.data if isinstance(result.data, list) else [result.data] if result.data else []

    return OrganizationListResponse(
        organizations=organizations,
        total=len(organizations)
    )


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    result = await supabase.table("organizations").select("*").eq("id", str(org_id)).is_null("deleted_at").single().execute_async()

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )

    return result.data


@router.delete("/{org_id}", response_model=DeleteOrganizationResponse)
async def delete_organization(
    org_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    org_result = await supabase.table("organizations").select("id, deleted_at").eq("id", str(org_id)).single().execute_async()

    if not org_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )

    if org_result.data.get("deleted_at"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization is already archived"
        )

    # Atomic DB cascade: soft-delete the org's active profiles AND the org in a
    # single transaction (migration 105). A failure rolls everything back, so we
    # never reach the auth-ban step below with a half-mutated DB. call_rpc maps
    # RpcError -> a v2 domain exception, which the global handlers turn into the
    # right HTTP status.
    rpc_result = await call_rpc(
        supabase, "admin_archive_organization", {"p_org_id": str(org_id)}
    )

    # Post-commit, best-effort: ban the affected auth users and drop their cached
    # profiles. These are external Auth-API calls that cannot live in the DB
    # transaction; the safe ordering (DB first, ban after) means a ban failure
    # only leaves a transient un-banned user under an archived org — never the
    # reverse — and self-heals on retry.
    user_ids = (rpc_result or {}).get("user_ids") or []
    if user_ids:
        try:
            await supabase.ban_users_batch([str(uid) for uid in user_ids], ban=True)
        except Exception as ban_err:
            logger.warning(
                "admin_archive_org_ban_failed",
                extra={
                    "event": "admin_archive_org_ban_failed",
                    "organization_id": str(org_id),
                    "error": str(ban_err),
                },
            )
        for user_id in user_ids:
            invalidate_profile_cache(str(user_id))

    return DeleteOrganizationResponse(
        message="Organization archived successfully",
        organization_id=org_id
    )


@router.post("/{org_id}/restore", response_model=DeleteOrganizationResponse)
async def restore_organization(
    org_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    org_result = await supabase.table("organizations").select("id, deleted_at").eq("id", str(org_id)).single().execute_async()

    if not org_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )

    if not org_result.data.get("deleted_at"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization is not archived"
        )

    # Atomic DB cascade: clear deleted_at on the org AND on the profiles that
    # were archived with it, in one transaction (migration 105).
    rpc_result = await call_rpc(
        supabase, "admin_restore_organization", {"p_org_id": str(org_id)}
    )

    # Post-commit, best-effort: unban the restored auth users and drop their
    # cached profiles. (Same ordering rationale as archive above.)
    user_ids = (rpc_result or {}).get("user_ids") or []
    if user_ids:
        try:
            await supabase.ban_users_batch([str(uid) for uid in user_ids], ban=False)
        except Exception as ban_err:
            logger.warning(
                "admin_restore_org_unban_failed",
                extra={
                    "event": "admin_restore_org_unban_failed",
                    "organization_id": str(org_id),
                    "error": str(ban_err),
                },
            )
        for user_id in user_ids:
            invalidate_profile_cache(str(user_id))

    return DeleteOrganizationResponse(
        message="Organization restored successfully",
        organization_id=org_id
    )


@router.get("/{org_id}/credits")
async def get_organization_credits(
    org_id: UUID,
    current_user: CurrentUser = Depends(require_staff),
):
    """The org's credit budget. This is the whole billing model — there are no
    plans, so an org's caps are the only thing gating usage.
    """
    supabase = get_supabase_admin_client()

    usage = await supabase.table("usage_credits") \
        .select("credit_type, total, used, period_start") \
        .eq("organization_id", str(org_id)) \
        .execute_async()

    credits = []
    for row in (usage.data or []):
        total = row["total"]
        used = row["used"]
        credits.append({
            "credit_type": row["credit_type"],
            "total": total,
            "used": used,
            "remaining": "unlimited" if total == -1 else max(total - used, 0),
            "period_start": row.get("period_start"),
        })

    return {"organization_id": str(org_id), "credits": credits}


@router.put("/{org_id}/credits")
async def set_organization_credits(
    org_id: UUID,
    req: OrgCreditsUpdate,
    current_user: CurrentUser = Depends(require_staff),
):
    """Raise or lower an org's credit caps. `used` is preserved."""
    if req.intake_total is None and req.interview_total is None:
        raise HTTPException(status_code=400, detail="No credit totals to update")

    await set_org_budget(
        str(org_id),
        intake_total=req.intake_total,
        interview_total=req.interview_total,
    )
    return await get_organization_credits(org_id, current_user)


@router.post("/{org_id}/migrate-user")
async def migrate_user_to_org(
    org_id: UUID,
    req: MigrateUserRequest,
    current_user: CurrentUser = Depends(require_staff),
):
    """Move a user (and the requisitions they created) into another org.

    Seats are unlimited: an org is capped by its credit budget, not by a head
    count, so there is no membership check here.
    """
    supabase = get_supabase_admin_client()

    org_result = await supabase.table("organizations") \
        .select("id, name") \
        .eq("id", str(org_id)) \
        .is_("deleted_at", "null") \
        .single() \
        .execute_async()
    if not org_result.data:
        raise HTTPException(404, "Target organization not found")

    profile_result = await supabase.table("profiles") \
        .select("id, email, organization_id") \
        .eq("id", str(req.user_id)) \
        .is_("deleted_at", "null") \
        .single() \
        .execute_async()
    if not profile_result.data:
        raise HTTPException(404, "User not found")

    source_org_id = profile_result.data["organization_id"]
    if source_org_id == str(org_id):
        raise HTTPException(409, "User is already in this organization")

    await supabase.table("requisitions") \
        .update({"organization_id": str(org_id)}) \
        .eq("organization_id", source_org_id) \
        .eq("created_by", str(req.user_id)) \
        .execute_async()

    await supabase.table("profiles") \
        .update({"organization_id": str(org_id)}) \
        .eq("id", str(req.user_id)) \
        .execute_async()

    invalidate_profile_cache(str(req.user_id))

    remaining_members = await supabase.table("profiles") \
        .select("id") \
        .eq("organization_id", source_org_id) \
        .is_("deleted_at", "null") \
        .count_async()

    if remaining_members == 0:
        await supabase.table("organizations") \
            .update({"deleted_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("id", source_org_id) \
            .execute_async()

    return {
        "message": "User migrated successfully",
        "user_id": str(req.user_id),
        "source_org_id": source_org_id,
        "target_org_id": str(org_id),
    }
