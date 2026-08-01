"""
Pipeline routes — candidate list + candidate-level mutations.

  GET    /roles/{id}/candidates
  POST   /roles/{id}/candidates
  POST   /roles/{id}/candidates/{cid}/rounds
  DELETE /roles/{id}/candidates/{cid}/rounds/{cr_id}
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.api.v2.schemas.candidate import (
    AddCustomRoundRequest,
    CreateCandidateRequest,
)
from app.api.v2.services import pipeline_service


router = APIRouter(tags=["v2/pipeline"])


@router.get("/roles/{role_id}/candidates")
async def get_role_candidates(
    role_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await pipeline_service.get_role_candidates(
        supabase, current.organization_id_str, role_id
    )


@router.post(
    "/roles/{role_id}/candidates",
    status_code=status.HTTP_201_CREATED,
)
async def add_candidate(
    role_id: UUID,
    body: CreateCandidateRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await pipeline_service.add_candidate(
        supabase, current.organization_id_str, role_id, body
    )


@router.post(
    "/roles/{role_id}/candidates/{candidate_id}/rounds",
    status_code=status.HTTP_201_CREATED,
)
async def add_candidate_custom_round(
    role_id: UUID,
    candidate_id: UUID,
    body: AddCustomRoundRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await pipeline_service.add_custom_round(
        supabase, current.organization_id_str, role_id, candidate_id, body
    )


@router.delete(
    "/roles/{role_id}/candidates/{candidate_id}/rounds/{cr_id}"
)
async def delete_candidate_round(
    role_id: UUID,
    candidate_id: UUID,
    cr_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await pipeline_service.delete_candidate_round(
        supabase, current.organization_id_str, role_id, candidate_id, cr_id
    )
