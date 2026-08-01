"""
Intake session routes.

  POST /intake/sessions      → create draft requisition + session, fire prefill Lambda
  GET  /intake/sessions/{id} → fetch session by ID (RLS enforces org scoping)
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.api.v2.schemas.intake import (
    CreateSessionRequest,
    CreateSessionResponse,
    IntakeSessionResponse,
    ListSessionsResponse,
)
from app.services.intake_session_service import IntakeSessionService
from app.services.intake_v2_feature_flag import is_intake_v2_enabled

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/intake/sessions", tags=["v2/intake"])


@router.post("", response_model=CreateSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: CreateSessionRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> CreateSessionResponse:
    if not await is_intake_v2_enabled(supabase, current.organization_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="v2 intake is not enabled for your organization",
        )
    service = IntakeSessionService(supabase_client=supabase)
    try:
        return await service.create_session(
            user_id=current.user.id,
            org_id=current.organization_id,
            form_data=payload.form_data,
            entry_point=payload.entry_point,
            requisition_id=payload.requisition_id,
        )
    except RuntimeError as e:
        logger.exception("create_session_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=ListSessionsResponse)
async def list_sessions(
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> ListSessionsResponse:
    """B1.1: List the caller's intake sessions (newest first, max 50)."""
    service = IntakeSessionService(supabase_client=supabase)
    return await service.list_user_sessions(
        user_id=current.user.id,
        organization_id=current.organization_id,
    )


@router.get("/{session_id}", response_model=IntakeSessionResponse)
async def get_session(
    session_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> IntakeSessionResponse:
    service = IntakeSessionService(supabase_client=supabase)
    try:
        return await service.get_session(
            session_id=session_id,
            user_id=current.user.id,
            organization_id=current.organization_id,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Session not found")
