"""
Interviewer-feedback routes.

  POST /candidate-rounds/{cr_id}/feedback
  POST /candidate-rounds/{cr_id}/request-feedback
  POST /candidate-rounds/{cr_id}/reprocess
"""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.api.v2.schemas.feedback import (
    ReprocessRequest,
    RequestFeedbackRequest,
    SubmitFeedbackRequest,
)
from app.api.v2.services import feedback_service


router = APIRouter(tags=["v2/feedback"])


@router.post("/candidate-rounds/{cr_id}/feedback")
async def submit_feedback(
    cr_id: UUID,
    body: SubmitFeedbackRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await feedback_service.submit_feedback(
        supabase, current.organization_id_str, cr_id, body
    )


@router.post("/candidate-rounds/{cr_id}/request-feedback")
async def request_feedback(
    cr_id: UUID,
    body: RequestFeedbackRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await feedback_service.request_feedback(
        supabase, current.organization_id_str, cr_id, body
    )


@router.post("/candidate-rounds/{cr_id}/reprocess")
async def reprocess_feedback(
    cr_id: UUID,
    body: ReprocessRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await feedback_service.reprocess_feedback(
        supabase, current.organization_id_str, cr_id, body
    )
