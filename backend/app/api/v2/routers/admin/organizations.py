from fastapi import APIRouter, Depends, HTTPException, status, Query
from uuid import UUID
from pydantic import BaseModel
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
from app.api.v2.core.rpc import call_rpc

logger = get_logger(__name__)


class DeleteOrganizationResponse(BaseModel):
    message: str
    organization_id: UUID


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
