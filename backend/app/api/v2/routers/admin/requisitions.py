from fastapi import APIRouter, Depends, HTTPException, status, Query
from uuid import UUID
from pydantic import BaseModel
from typing import Optional, List
from app.dependencies import require_staff, CurrentUser
from app.models.requisitions import (
    RequisitionCreate,
    RequisitionUpdate,
    RequisitionResponse,
    RequisitionListResponse,
    RequisitionWithPlanResponse,
    IntakeUpdate,
    InterviewPlanCreate,
    InterviewPlanResponse,
    RoundCreate,
    RoundUpdate,
    RoundResponse,
    RoundWithQuestionsResponse,
    RoundReorderRequest,
    FeedbackQuestionCreate,
    FeedbackQuestionUpdate,
    FeedbackQuestionResponse,
    SAMPLE_INTERVIEW_PLAN,
)
from app.services.requisition_service import get_requisition_service


router = APIRouter(prefix="/requisitions", tags=["Requisitions"])


class MessageResponse(BaseModel):
    message: str


class DeleteResponse(BaseModel):
    message: str
    id: UUID


class SamplePlanResponse(BaseModel):
    sample: dict


class StatusUpdate(BaseModel):
    status: str


class IntakeCallResponse(BaseModel):
    session_token: str
    requisition_id: str


# ============================================
# SAMPLE DATA ENDPOINT
# ============================================

@router.get("/sample-plan", response_model=SamplePlanResponse)
async def get_sample_interview_plan(
    current_user: CurrentUser = Depends(require_staff)
):
    return SamplePlanResponse(sample=SAMPLE_INTERVIEW_PLAN)


# ============================================
# REQUISITION CRUD
# ============================================

@router.post(
    "/organizations/{org_id}",
    response_model=RequisitionResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_requisition(
    org_id: UUID,
    req: RequisitionCreate,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    return await service.create_requisition(str(org_id), req, str(current_user.id))


@router.get(
    "/organizations/{org_id}",
    response_model=RequisitionListResponse
)
async def list_requisitions(
    org_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: CurrentUser = Depends(require_staff),
):
    service = get_requisition_service()
    requisitions, total = await service.list_requisitions(str(org_id), page=page, page_size=page_size)
    return RequisitionListResponse(requisitions=requisitions, total=total)


@router.get(
    "/organizations/{org_id}/deleted",
    response_model=RequisitionListResponse
)
async def list_deleted_requisitions(
    org_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    requisitions, total = await service.list_requisitions(str(org_id), include_deleted=True)
    return RequisitionListResponse(requisitions=requisitions, total=total)


@router.get(
    "/{req_id}",
    response_model=RequisitionResponse
)
async def get_requisition(
    req_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    return await service.get_requisition(str(req_id))


@router.get(
    "/{req_id}/with-plan",
    response_model=RequisitionWithPlanResponse
)
async def get_requisition_with_plan(
    req_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    return await service.get_requisition_with_plan(str(req_id))


@router.put(
    "/{req_id}",
    response_model=RequisitionResponse
)
async def update_requisition(
    req_id: UUID,
    req: RequisitionUpdate,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    return await service.update_requisition(str(req_id), req)


@router.put(
    "/{req_id}/intake",
    response_model=RequisitionResponse
)
async def update_intake(
    req_id: UUID,
    intake: IntakeUpdate,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    return await service.update_intake(str(req_id), intake)


@router.put(
    "/{req_id}/status",
    response_model=RequisitionResponse
)
async def update_requisition_status(
    req_id: UUID,
    status_update: StatusUpdate,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    return await service.update_status(
        str(req_id), status_update.status,
        allowed_statuses=['intake_pending', 'planned']
    )


@router.post("/{req_id}/intake-call", response_model=IntakeCallResponse)
async def create_intake_call_session(
    req_id: UUID,
    current_user: CurrentUser = Depends(require_staff),
):
    service = get_requisition_service()
    result = await service.create_intake_call_session(str(req_id))
    return IntakeCallResponse(**result)


@router.delete(
    "/{req_id}",
    response_model=DeleteResponse
)
async def delete_requisition(
    req_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    result = await service.soft_delete_requisition(str(req_id))
    return DeleteResponse(message=result["message"], id=UUID(result["id"]))


@router.post(
    "/{req_id}/restore",
    response_model=DeleteResponse
)
async def restore_requisition(
    req_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    result = await service.restore_requisition(str(req_id))
    return DeleteResponse(message=result["message"], id=UUID(result["id"]))


# ============================================
# INTERVIEW PLAN BULK OPERATIONS
# ============================================

@router.post(
    "/{req_id}/plan",
    response_model=InterviewPlanResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_interview_plan(
    req_id: UUID,
    plan: InterviewPlanCreate,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    return await service.create_interview_plan(str(req_id), plan)


@router.get(
    "/{req_id}/plan",
    response_model=InterviewPlanResponse
)
async def get_interview_plan(
    req_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    return await service.get_interview_plan(str(req_id))


@router.put(
    "/{req_id}/plan",
    response_model=InterviewPlanResponse
)
async def update_interview_plan(
    req_id: UUID,
    plan: InterviewPlanCreate,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    return await service.update_interview_plan(str(req_id), plan)


@router.delete(
    "/{req_id}/plan",
    response_model=MessageResponse
)
async def delete_interview_plan(
    req_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    result = await service.delete_interview_plan(str(req_id))
    return MessageResponse(message=result["message"])


# ============================================
# GRANULAR ROUND OPERATIONS
# ============================================

@router.post(
    "/{req_id}/rounds",
    response_model=RoundWithQuestionsResponse,
    status_code=status.HTTP_201_CREATED
)
async def add_round(
    req_id: UUID,
    round_data: RoundCreate,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    return await service.add_round(str(req_id), round_data)


@router.put(
    "/rounds/{round_id}",
    response_model=RoundResponse
)
async def update_round(
    round_id: UUID,
    round_update: RoundUpdate,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    return await service.update_round(str(round_id), round_update)


@router.delete(
    "/rounds/{round_id}",
    response_model=DeleteResponse
)
async def delete_round(
    round_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    result = await service.delete_round(str(round_id))
    return DeleteResponse(message=result["message"], id=UUID(result["id"]))


@router.post(
    "/rounds/{round_id}/restore",
    response_model=DeleteResponse
)
async def restore_round(
    round_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    result = await service.restore_round(str(round_id))
    return DeleteResponse(message=result["message"], id=UUID(result["id"]))


@router.put(
    "/{req_id}/rounds/reorder",
    response_model=MessageResponse
)
async def reorder_rounds(
    req_id: UUID,
    reorder_data: RoundReorderRequest,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    result = await service.reorder_rounds(str(req_id), reorder_data)
    return MessageResponse(message=result["message"])


# ============================================
# GRANULAR FEEDBACK QUESTION OPERATIONS
# ============================================

@router.post(
    "/rounds/{round_id}/questions",
    response_model=FeedbackQuestionResponse,
    status_code=status.HTTP_201_CREATED
)
async def add_question(
    round_id: UUID,
    question_data: FeedbackQuestionCreate,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    return await service.add_question(str(round_id), question_data)


@router.put(
    "/questions/{question_id}",
    response_model=FeedbackQuestionResponse
)
async def update_question(
    question_id: UUID,
    question_update: FeedbackQuestionUpdate,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    return await service.update_question(str(question_id), question_update)


@router.delete(
    "/questions/{question_id}",
    response_model=DeleteResponse
)
async def delete_question(
    question_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    result = await service.delete_question(str(question_id))
    return DeleteResponse(message=result["message"], id=UUID(result["id"]))


@router.post(
    "/questions/{question_id}/restore",
    response_model=DeleteResponse
)
async def restore_question(
    question_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    service = get_requisition_service()
    result = await service.restore_question(str(question_id))
    return DeleteResponse(message=result["message"], id=UUID(result["id"]))
