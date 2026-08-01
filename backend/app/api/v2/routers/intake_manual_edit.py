"""PATCH /api/v2/intake/sessions/{id}/answers — manual answer edit (spec §6.6 B2.1)."""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.api.v2.schemas.intake import PatchAnswersRequest, PatchAnswersResponse
from app.services.intake_manual_edit_service import IntakeManualEditService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/intake/sessions", tags=["v2/intake-manual-edit"])


@router.patch("/{session_id}/answers", response_model=PatchAnswersResponse)
async def patch_answers(
    session_id: UUID,
    payload: PatchAnswersRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> PatchAnswersResponse:
    service = IntakeManualEditService(supabase_client=supabase)
    try:
        applied = await service.apply_patch(
            session_id=session_id,
            user_id=current.user.id,
            organization_id=current.organization_id,
            patch=payload.patch,
        )
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    except Exception as e:
        logger.exception("patch_answers_failed", session_id=str(session_id))
        raise HTTPException(status_code=500, detail=f"failed to apply patch: {e}")

    return PatchAnswersResponse(applied=applied)
