"""
Recording-URL + transcript read routes.

  GET /candidate-rounds/{cr_id}/recording-url
  GET /candidate-rounds/{cr_id}/transcript
"""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.api.v2.services import recording_service


router = APIRouter(tags=["v2/recordings"])


@router.get("/candidate-rounds/{cr_id}/recording-url")
async def get_recording_url(
    cr_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await recording_service.get_recording_url(
        supabase, current.organization_id_str, cr_id
    )


@router.get("/candidate-rounds/{cr_id}/transcript")
async def get_transcript(
    cr_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await recording_service.get_transcript(
        supabase, current.organization_id_str, cr_id
    )
