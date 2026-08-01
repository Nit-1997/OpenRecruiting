"""
Shared-plan (rounds + feedback_questions) routes.

  GET    /roles/{id}/plan
  POST   /roles/{id}/plan/rounds
  PUT    /plan/rounds/{round_id}
  DELETE /plan/rounds/{round_id}
  POST   /roles/{id}/plan/rounds/reorder
  POST   /plan/rounds/{round_id}/questions
  PUT    /plan/questions/{question_id}
  DELETE /plan/questions/{question_id}
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.api.v2.schemas.round import (
    AddQuestionRequest,
    AddRoundRequest,
    ReorderRoundItem,
    RolePlanResponse,
    UpdateQuestionRequest,
    UpdateRoundRequest,
)
from app.api.v2.services import plan_service


router = APIRouter(tags=["v2/plan"])


@router.get("/roles/{role_id}/plan", response_model=RolePlanResponse)
async def get_role_plan(
    role_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await plan_service.get_role_plan(
        supabase, current.organization_id_str, role_id
    )


@router.post(
    "/roles/{role_id}/plan/rounds",
    status_code=status.HTTP_201_CREATED,
)
async def add_round(
    role_id: UUID,
    body: AddRoundRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await plan_service.add_round(
        supabase, current.organization_id_str, role_id, body
    )


@router.put("/plan/rounds/{round_id}")
async def update_round(
    round_id: UUID,
    body: UpdateRoundRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await plan_service.update_round(
        supabase, current.organization_id_str, round_id, body
    )


@router.delete("/plan/rounds/{round_id}")
async def delete_round(
    round_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await plan_service.delete_round(
        supabase, current.organization_id_str, round_id
    )


@router.post("/roles/{role_id}/plan/rounds/reorder")
async def reorder_rounds(
    role_id: UUID,
    body: List[ReorderRoundItem],
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
) -> dict:
    return await plan_service.reorder_rounds(
        supabase, current.organization_id_str, role_id, body, if_match
    )


@router.post(
    "/plan/rounds/{round_id}/questions",
    status_code=status.HTTP_201_CREATED,
)
async def add_question(
    round_id: UUID,
    body: AddQuestionRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await plan_service.add_question(
        supabase, current.organization_id_str, round_id, body
    )


@router.put("/plan/questions/{question_id}")
async def update_question(
    question_id: UUID,
    body: UpdateQuestionRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await plan_service.update_question(
        supabase, current.organization_id_str, question_id, body
    )


@router.delete("/plan/questions/{question_id}")
async def delete_question(
    question_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    return await plan_service.delete_question(
        supabase, current.organization_id_str, question_id
    )
