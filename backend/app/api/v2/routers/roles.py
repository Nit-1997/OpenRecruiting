"""
Role (requisition) header + open/close lifecycle routes.

  GET   /roles                — paginated list for the caller's org
                                 (items + total + status_counts + pipeline)
  GET   /roles/{id}           — role header (with counts)
  POST  /roles/{id}/close
  POST  /roles/{id}/reopen
"""

from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.api.v2.schemas.role import RoleHeaderResponse, RolesListResponse
from app.api.v2.services import role_service


router = APIRouter(tags=["v2/roles"])

# Canonical requisition status enum per spec §15. UI labels (Open/Pending/Closed)
# are mapped to these values by the frontend before the call.
StatusFilter = Literal["planned", "intake_pending", "closed"]


@router.get("/roles", response_model=RolesListResponse)
async def list_roles(
    status: Optional[StatusFilter] = Query(
        None,
        description=(
            "Filter by canonical requisition status. Omit for all roles. "
            "UI tab → canonical: Open=planned, Pending=intake_pending, "
            "Closed=closed."
        ),
    ),
    page: int = Query(1, ge=1, description="1-indexed page number."),
    page_size: int = Query(
        10,
        ge=1,
        le=100,
        description=(
            "Page size. Default 10, max 100. The FE rail uses 10; admin "
            "tools may bump this up to 100."
        ),
    ),
    q: Optional[str] = Query(
        None,
        description=(
            "Case-insensitive substring search across role_title and "
            "role_location. Applied server-side so search works across all "
            "pages, not just the visible slice. status_counts in the "
            "response remain org-wide regardless of `q`."
        ),
    ),
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> RolesListResponse:
    return await role_service.list_roles(
        supabase,
        current.organization_id_str,
        status=status,
        page=page,
        page_size=page_size,
        q=q,
    )


@router.get("/roles/{role_id}", response_model=RoleHeaderResponse)
async def get_role(
    role_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> RoleHeaderResponse:
    return await role_service.get_role_header(
        supabase, current.organization_id_str, role_id
    )


@router.post("/roles/{role_id}/close")
async def close_role(
    role_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await role_service.close_role(
        supabase, current.organization_id_str, role_id
    )


@router.post("/roles/{role_id}/reopen")
async def reopen_role(
    role_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await role_service.reopen_role(
        supabase, current.organization_id_str, role_id
    )
