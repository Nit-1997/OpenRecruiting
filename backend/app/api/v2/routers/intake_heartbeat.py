"""
Intake v2 session heartbeat route.

  POST /intake/sessions/:id/heartbeat?paused={bool}
"""
from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.services.intake_heartbeat_service import (
    HeartbeatNoLockError,
    IntakeHeartbeatService,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/intake/sessions", tags=["v2/intake"])


@router.post("/{session_id}/heartbeat")
async def heartbeat(
    session_id: UUID,
    paused: bool = Query(False),
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    svc = IntakeHeartbeatService(supabase)
    try:
        ts = await svc.ping(session_id=session_id, user_id=current.user.id, paused=paused)
    except HeartbeatNoLockError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="modality_lock_not_held",
        )
    return {"ok": True, "last_heartbeat_at": ts}
