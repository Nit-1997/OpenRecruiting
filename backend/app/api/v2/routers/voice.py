"""POST /api/v2/intake/sessions/:id/voice/start — proxies WebRTC offer to voice-agent."""

from __future__ import annotations

from uuid import UUID

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.api.v2.core.dependencies import CurrentUserWithOrg, get_current_user_with_org, get_supabase
from app.api.v2.schemas.intake import VoiceStartRequest, VoiceStartResponse
from app.config import get_settings
from app.services.modality_lock import ModalityConflictError, require_no_other_modality
from app.services.voice_v2_client import request_voice_offer

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/intake/sessions", tags=["v2/intake-voice"])


@router.post("/{session_id}/voice/start", response_model=VoiceStartResponse)
async def voice_start(
    session_id: UUID,
    payload: VoiceStartRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> VoiceStartResponse:
    """Forward the user's WebRTC offer to voice-agent and return the answer.

    The voice agent does its own session-row lookup, modality lock, and pipeline boot.
    This endpoint exists so the frontend never talks to the voice agent directly
    (the voice agent is internal-only — accessible only to backend).
    """
    from fastapi.responses import JSONResponse
    try:
        await require_no_other_modality(
            supabase,
            session_id=session_id,
            self_modality="voice",
            organization_id=current.organization_id,
            user_id=current.user.id,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="session not found")
    except ModalityConflictError as e:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "another mode is currently active — end the existing session first.",
                "held": e.held,
                "requested": e.requested,
            },
        )

    settings = get_settings()
    voice_url = settings.VOICE_AGENT_V2_URL
    if not voice_url:
        logger.error("voice_agent_v2_url_unset")
        raise HTTPException(status_code=500, detail="voice agent v2 URL not configured")

    try:
        result = await request_voice_offer(
            voice_agent_url=voice_url,
            session_id=str(session_id),
            offer_sdp=payload.sdp,
            offer_type=payload.type,
        )
    except RuntimeError as e:
        msg = str(e)
        logger.info("voice_start_rejected", session_id=str(session_id), reason=msg)
        if "conflict" in msg.lower() or "modality" in msg.lower():
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.error("voice_agent_v2_unreachable", session_id=str(session_id), error=str(e))
        raise HTTPException(status_code=502, detail="voice agent unreachable")
    except httpx.HTTPStatusError as e:
        logger.error(
            "voice_agent_v2_http_error",
            session_id=str(session_id),
            status=e.response.status_code,
        )
        raise HTTPException(status_code=502, detail=f"voice agent returned {e.response.status_code}")

    return VoiceStartResponse(sdp=result["sdp"], type=result.get("type", "answer"))
