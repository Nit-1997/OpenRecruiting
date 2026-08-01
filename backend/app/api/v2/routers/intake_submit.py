"""POST submit + publish endpoints for v2 intake sessions."""
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
    PublishRequest,
    PublishResponse,
    SubmitResponse,
)
from app.services.intake_publish_service import (
    IntakePublishError,
    IntakePublishService,
)
from app.services.intake_submit_service import (
    IntakeSubmitError,
    IntakeSubmitService,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/intake/sessions", tags=["v2/intake-submit"])


@router.post(
    "/{session_id}/submit",
    response_model=SubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_session(
    session_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> SubmitResponse:
    """Flip session status to 'submitted' and invoke the v2 scorecard Lambda async."""
    service = IntakeSubmitService(supabase_client=supabase)
    try:
        result = await service.submit(
            session_id=session_id,
            user_id=current.user.id,
            organization_id=current.organization_id,
        )
    except IntakeSubmitError as e:
        logger.warning("submit_rejected", session_id=str(session_id), reason=e.message)
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return SubmitResponse(session_id=UUID(result["session_id"]), status=result["status"])


@router.post(
    "/{session_id}/publish",
    response_model=PublishResponse,
)
async def publish_session(
    session_id: UUID,
    payload: PublishRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> PublishResponse:
    """Write the (possibly edited) interview_plan to canonical tables and
    flip requisition + session status to their published states.
    """
    service = IntakePublishService(supabase_client=supabase)
    try:
        result = await service.publish(
            session_id=session_id,
            user_id=current.user.id,
            organization_id=current.organization_id,
            edited_plan=payload.interview_plan,
        )
    except IntakePublishError as e:
        logger.warning("publish_rejected", session_id=str(session_id), reason=e.message)
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return PublishResponse(
        session_id=UUID(result["session_id"]),
        requisition_id=UUID(result["requisition_id"]),
        redirect_url=result["redirect_url"],
    )
