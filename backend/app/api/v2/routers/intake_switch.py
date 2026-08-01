"""POST /api/v2/intake/sessions/:id/switch?to=text|voice — orchestrate handoff between modalities.

To-text path:
  1. Tell voice agent to drain (graceful EndFrame, then hard cancel fallback).
  2. On success, flip active_modality='text'.
  3. Return current session state — frontend swaps UI without remounting.

To-voice path:
  1. Acquire active_modality='voice' (409 if text already held by some other route).
  2. Return a hint that the frontend should follow up with POST .../voice/start to
     run the WebRTC offer/answer dance. The lock is already held, so /voice/start
     becomes idempotent (no second acquire attempt).

We never flip the lock without proof that the previous holder is gone. If drain
fails (timeout, 5xx), return 502 — the user retries. This avoids the worst-case
silent split-brain where Pipecat is still talking but the UI thinks text owns.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.api.v2.core.dependencies import CurrentUserWithOrg, get_current_user_with_org, get_supabase
from app.config import get_settings
from app.services.intake_session_service import IntakeSessionService
from app.services.modality_lock import ModalityConflictError, set_modality
from app.services.voice_agent_client import VoiceAgentClient, VoiceAgentDrainError

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/intake/sessions", tags=["v2/intake-switch"])


@router.post("/{session_id}/switch")
async def switch_modality(
    session_id: UUID,
    to: Literal["text", "voice", "none"] = Query(..., description="Target modality (none = end conversation)"),
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
):
    if to not in ("text", "voice", "none"):
        return JSONResponse(status_code=400, content={"detail": "invalid target modality"})

    if to == "none":
        # OWNERSHIP CHECK — scope to (user_id, organization_id) before any side-effect.
        service = IntakeSessionService(supabase_client=supabase)
        try:
            session = await service.get_session(
                session_id=session_id,
                user_id=current.user.id,
                organization_id=current.organization_id,
            )
        except LookupError:
            return JSONResponse(status_code=404, content={"detail": "session not found"})

        current_modality = getattr(session, "active_modality", None)

        # Idempotent path: nothing to clear, no drain, no DB write.
        if current_modality is None:
            return JSONResponse(
                status_code=200,
                content={
                    "active_modality": None,
                    "drained": None,
                    "session": session.model_dump(mode="json"),
                },
            )

        drain_result = None
        if current_modality == "voice":
            # Voice is live — drain Pipecat before clearing the lock so we never
            # end up with the agent still talking while the DB says idle.
            client = VoiceAgentClient(settings=get_settings())
            try:
                drain_result = await client.drain_session(session_id=session_id)
            except VoiceAgentDrainError as e:
                logger.error(
                    "switch_to_none_drain_failed",
                    session_id=str(session_id),
                    error=str(e),
                )
                return JSONResponse(
                    status_code=502,
                    content={
                        "detail": "voice agent did not drain cleanly — please try again",
                    },
                )

        try:
            await set_modality(
                supabase,
                session_id=session_id,
                modality=None,
                organization_id=current.organization_id,
                user_id=current.user.id,
            )
        except Exception as e:
            logger.exception("switch_to_none_set_modality_failed", session_id=str(session_id))
            return JSONResponse(
                status_code=500,
                content={"detail": "failed to clear modality lock"},
            )

        return JSONResponse(
            status_code=200,
            content={
                "active_modality": None,
                "drained": drain_result,
                "session": session.model_dump(mode="json"),
            },
        )

    if to == "text":
        # OWNERSHIP CHECK — must happen before any external side-effect.
        # get_session scopes to (user_id, organization_id) and raises LookupError
        # for cross-tenant session_ids, so an attacker can't drain another org's call.
        service = IntakeSessionService(supabase_client=supabase)
        try:
            session = await service.get_session(
                session_id=session_id,
                user_id=current.user.id,
                organization_id=current.organization_id,
            )
        except LookupError:
            return JSONResponse(status_code=404, content={"detail": "session not found"})

        client = VoiceAgentClient(settings=get_settings())
        try:
            drain_result = await client.drain_session(session_id=session_id)
        except VoiceAgentDrainError as e:
            logger.error("switch_to_text_drain_failed", session_id=str(session_id), error=str(e))
            return JSONResponse(
                status_code=502,
                content={
                    "detail": "voice agent did not drain cleanly — please try again",
                    "error": str(e),
                },
            )

        try:
            await set_modality(
                supabase,
                session_id=session_id,
                modality="text",
                organization_id=current.organization_id,
                user_id=current.user.id,
            )
        except Exception as e:
            logger.exception("switch_set_modality_failed", session_id=str(session_id))
            return JSONResponse(
                status_code=500,
                content={"detail": "failed to update modality lock"},
            )

        return JSONResponse(
            status_code=200,
            content={
                "active_modality": "text",
                "drained": drain_result,
                "session": session.model_dump(mode="json"),
            },
        )

    # to == "voice"
    # Symmetric with to=text: an explicit, user-initiated switch to voice is a
    # FORCED handoff. Text mode is stateless request/response SSE — there is no
    # live connection to drain — and the only lock that could be set is the user's
    # OWN text lock, so we SET the lock to 'voice' unconditionally rather than
    # acquire-with-409. The old acquire-with-409 path made a normal chat→voice
    # switch fail with a spurious 409 because the user's own text lock was still
    # held; routing this through the deterministic acquire RPC would re-introduce
    # that bug, so the contended acquire lives at POST .../voice/start instead.
    #
    # BE-G2: should a deterministic ModalityConflictError ever reach here, surface
    # it as a proper 409 (not the old generic 500) — the conflict now carries
    # definite info from the RPC, so a 5xx would be misleading.
    service = IntakeSessionService(supabase_client=supabase)
    try:
        await service.get_session(
            session_id=session_id,
            user_id=current.user.id,
            organization_id=current.organization_id,
        )
    except LookupError:
        return JSONResponse(status_code=404, content={"detail": "session not found"})

    try:
        await set_modality(
            supabase,
            session_id=session_id,
            modality="voice",
            organization_id=current.organization_id,
            user_id=current.user.id,
        )
    except ModalityConflictError as e:
        logger.info("switch_to_voice_conflict", session_id=str(session_id), held=e.held)
        return JSONResponse(
            status_code=409,
            content={
                "detail": "another mode is currently active — end the existing session first.",
                "held": e.held,
                "requested": e.requested,
            },
        )
    except Exception as e:
        logger.exception("switch_to_voice_set_modality_failed", session_id=str(session_id))
        return JSONResponse(
            status_code=500,
            content={"detail": "failed to update modality lock", "error": str(e)},
        )

    return JSONResponse(
        status_code=200,
        content={"active_modality": "voice", "next_step": "voice_start"},
    )
