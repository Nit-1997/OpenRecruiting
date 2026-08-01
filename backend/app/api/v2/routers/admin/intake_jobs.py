from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID

from app.dependencies import require_staff, CurrentUser
from app.services.intake_job_service import get_intake_job_service, IntakeJobServiceError
from app.services.requisition_service import get_requisition_service
from app.services.supabase import get_supabase_admin_client
from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Intake Jobs"])


class CreateIntakeJobRequest(BaseModel):
    requisition_id: UUID
    intake_transcript: str = Field(..., min_length=10)


class IntakeJobResponse(BaseModel):
    status: str
    requisition_id: UUID
    reason: Optional[str] = None


class IntakeStatusResponse(BaseModel):
    found: bool
    requisition_id: UUID
    intake_processing_status: Optional[str] = None
    intake_processing_error: Optional[str] = None
    intake_processing_started_at: Optional[str] = None
    intake_processing_completed_at: Optional[str] = None
    intake_processing_stage: Optional[str] = None
    intake_summary: Optional[str] = None


@router.post(
    "/intake-jobs",
    response_model=IntakeJobResponse,
)
async def create_intake_job(
    request: CreateIntakeJobRequest,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()
    req_id = str(request.requisition_id)

    req_result = await supabase.table("requisitions")\
        .select("id")\
        .eq("id", req_id)\
        .is_null("deleted_at")\
        .execute_async()

    if not req_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Requisition not found"
        )

    await supabase.table("requisitions")\
        .update({"intake_transcript": request.intake_transcript})\
        .eq("id", req_id)\
        .execute_async()

    service = get_intake_job_service()

    try:
        result = await service.trigger_intake_processing(req_id)
    except IntakeJobServiceError as e:
        logger.error(f"IntakeJob API: {e.error_code} - {e.message}")
        if e.error_code == "ResourceNotFoundException":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Intake processing service unavailable"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to submit intake job: {e.message}"
            )

    if result['status'] == 'rejected':
        return IntakeJobResponse(
            status="rejected",
            requisition_id=request.requisition_id,
            reason=result.get('reason'),
        )

    req_service = get_requisition_service()
    await req_service.delete_rounds_cascade(req_id)

    return IntakeJobResponse(
        status=result['status'],
        requisition_id=request.requisition_id,
        reason=result.get('reason')
    )


@router.get(
    "/intake-jobs/{requisition_id}/status",
    response_model=IntakeStatusResponse,
)
async def get_intake_status(
    requisition_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_intake_job_service()
    result = await service.get_processing_status(str(requisition_id))

    if not result['found']:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Requisition not found"
        )

    return IntakeStatusResponse(**result)
