"""
Candidate-round journey routes — schedule / reschedule / cancel.

  POST /candidate-rounds/{cr_id}/schedule
  PUT  /candidate-rounds/{cr_id}/schedule
  POST /candidate-rounds/{cr_id}/cancel
"""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.api.v2.schemas.interview import (
    RescheduleInterviewRequest,
    ScheduleInterviewRequest,
)
from app.api.v2.services import journey_service


router = APIRouter(tags=["v2/journey"])


@router.post("/candidate-rounds/{cr_id}/schedule")
async def schedule_candidate_round(
    cr_id: UUID,
    body: ScheduleInterviewRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await journey_service.schedule_candidate_round(
        supabase, current.organization_id_str, cr_id, body
    )


@router.put("/candidate-rounds/{cr_id}/schedule")
async def reschedule_candidate_round(
    cr_id: UUID,
    body: RescheduleInterviewRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await journey_service.reschedule_candidate_round(
        supabase, current.organization_id_str, cr_id, body
    )


@router.post("/candidate-rounds/{cr_id}/cancel")
async def cancel_candidate_round(
    cr_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await journey_service.cancel_candidate_round(
        supabase, current.organization_id_str, cr_id
    )
