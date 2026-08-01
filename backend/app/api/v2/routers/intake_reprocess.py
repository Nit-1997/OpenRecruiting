"""POST /api/v2/intake/sessions/{session_id}/reprocess — 'process till now'."""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.services.intake_reprocess_service import (
    IntakeReprocessError,
    IntakeReprocessService,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/intake/sessions", tags=["v2/intake-reprocess"])


@router.post("/{session_id}/reprocess", status_code=202)
async def reprocess_session(
    session_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
):
    service = IntakeReprocessService(supabase_client=supabase)
    try:
        result = await service.reprocess(
            session_id=session_id,
            user_id=current.user.id,
            organization_id=current.organization_id,
        )
    except IntakeReprocessError as e:
        return JSONResponse(status_code=e.status_code, content={"detail": e.message})
    return result
