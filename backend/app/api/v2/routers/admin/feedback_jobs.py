from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID

from app.dependencies import require_staff, CurrentUser
from app.services.feedback_job_service import get_feedback_job_service, FeedbackJobServiceError
from app.services.supabase import get_supabase_admin_client
from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Feedback Jobs"])


class CreateFeedbackJobRequest(BaseModel):
    candidate_round_id: UUID
    skip_prereq_check: bool = False
    new_feedback_transcript: Optional[str] = Field(None, min_length=10, description="Manual feedback transcript to save before processing")


class FeedbackJobResponse(BaseModel):
    status: str
    candidate_round_id: UUID
    reason: Optional[str] = None


class FeedbackStatusResponse(BaseModel):
    found: bool
    candidate_round_id: UUID
    processing_status: Optional[str] = None
    processing_error: Optional[str] = None
    processing_started_at: Optional[str] = None
    processing_completed_at: Optional[str] = None
    rating: Optional[str] = None
    summary: Optional[str] = None


class PrereqCheckResponse(BaseModel):
    candidate_round_id: UUID
    can_process: bool
    reason: str


@router.post(
    "/feedback-jobs",
    response_model=FeedbackJobResponse,
    summary="Trigger feedback processing",
    description="Manually trigger the feedback processing Lambda for a candidate round. Optionally provide a manual feedback transcript."
)
async def create_feedback_job(
    request: CreateFeedbackJobRequest,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_feedback_job_service()
    supabase = get_supabase_admin_client()

    try:
        if request.new_feedback_transcript:
            existing = await supabase.table("transcripts")\
                .select("id")\
                .eq("candidate_round_id", str(request.candidate_round_id))\
                .execute_async()

            if existing.data and len(existing.data) > 0:
                await supabase.table("transcripts")\
                    .update({"feedback_transcript": request.new_feedback_transcript})\
                    .eq("candidate_round_id", str(request.candidate_round_id))\
                    .execute_async()
            else:
                await supabase.table("transcripts")\
                    .insert({
                        "candidate_round_id": str(request.candidate_round_id),
                        "feedback_transcript": request.new_feedback_transcript,
                        "provider": "manual"
                    })\
                    .execute_async()

            logger.info(f"Saved manual feedback transcript for {request.candidate_round_id}")

        result = await service.trigger_feedback_processing(
            str(request.candidate_round_id),
            skip_prereq_check=request.skip_prereq_check or bool(request.new_feedback_transcript)
        )

        return FeedbackJobResponse(
            status=result['status'],
            candidate_round_id=request.candidate_round_id,
            reason=result.get('reason')
        )

    except FeedbackJobServiceError as e:
        logger.error(f"FeedbackJob API: {e.error_code} - {e.message}")

        if e.error_code == "ResourceNotFoundException":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Feedback processing service unavailable"
            )
        elif e.error_code == "InvalidRequestContentException":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid request"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to submit feedback job: {e.message}"
            )


@router.get(
    "/feedback-jobs/{candidate_round_id}/status",
    response_model=FeedbackStatusResponse,
    summary="Check feedback processing status",
    description="Get the current processing status for a candidate round"
)
async def get_feedback_status(
    candidate_round_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_feedback_job_service()
    result = await service.get_processing_status(str(candidate_round_id))

    if not result['found']:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate round not found"
        )

    return FeedbackStatusResponse(**result)


@router.get(
    "/feedback-jobs/{candidate_round_id}/prereq-check",
    response_model=PrereqCheckResponse,
    summary="Check prerequisites for feedback processing",
    description="Verify if a candidate round has all required data for feedback processing"
)
async def check_feedback_prerequisites(
    candidate_round_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_feedback_job_service()
    can_process, reason = await service.can_process_feedback(str(candidate_round_id))

    return PrereqCheckResponse(
        candidate_round_id=candidate_round_id,
        can_process=can_process,
        reason=reason
    )
