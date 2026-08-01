"""SSE endpoint for v2 intake text conversation.

POST /intake/sessions/:id/text/messages
Body: {"message": "user text"}
Response: text/event-stream

Events emitted (in order):
  event: text   data: "<json-encoded prose chunk>"
  event: tool   data: {"name": "...", "args": {...}}
  event: done   data: {"text": "...", "stop_reason": "...",
                       "user_turn_idx": int, "assistant_turn_idx": int}
  event: error  data: {"message": "..."}  (only on mid-stream failure)

Modality conflicts are returned as HTTP 409 BEFORE the stream opens (they're
detected synchronously by load_session inside run_text_turn).
"""

from __future__ import annotations

import json
from typing import AsyncIterator
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.dependencies import get_anthropic_async_client
from app.services.intake.text_runner import (
    ModalityConflictError,
    run_text_opening,
    run_text_turn,
)
from app.services.modality_lock import ModalityConflictError as _ModalityLockConflict, require_no_other_modality

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/intake/sessions", tags=["v2/intake-text"])

ANTHROPIC_MODEL = "claude-sonnet-4-6"


class TextMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10_000)

    @field_validator("message")
    @classmethod
    def _not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message cannot be empty or whitespace-only")
        return v


def _sse_event(event: str, data: object) -> str:
    """Format an SSE event. Data is JSON-encoded so newlines in prose are safe."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _sse_stream(
    supabase_client,
    anthropic_client,
    session_id: str,
    user_message: str,
) -> AsyncIterator[str]:
    try:
        async for kind, payload in run_text_turn(
            supabase_client=supabase_client,
            anthropic_client=anthropic_client,
            model=ANTHROPIC_MODEL,
            session_id=session_id,
            user_message=user_message,
        ):
            if kind == "text":
                yield _sse_event("text", payload)
            elif kind == "tool_call":
                yield _sse_event("tool", {
                    "name": payload.get("name"),
                    "args": payload.get("input", {}),
                })
            elif kind == "done":
                yield _sse_event("done", payload)
    except ModalityConflictError as e:
        yield _sse_event("error", {"message": str(e), "code": "modality_conflict"})
    except Exception as e:
        logger.exception("text_stream_failed", session_id=session_id)
        yield _sse_event("error", {"message": str(e)[:300], "code": "internal_error"})


@router.post("/{session_id}/text/messages")
async def post_text_message(
    session_id: UUID,
    payload: TextMessageRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
    anthropic=Depends(get_anthropic_async_client),
):
    """Stream the agent's response to a user text turn.

    Pre-flight: load the session and check active_modality. If voice is
    currently active, return 409 BEFORE opening the SSE stream.
    """
    from fastapi.responses import JSONResponse
    from intake_core.persistence import aload_session

    try:
        await require_no_other_modality(
            supabase,
            session_id=session_id,
            self_modality="text",
            organization_id=current.organization_id,
            user_id=current.user.id,
        )
        session = await aload_session(supabase, str(session_id))
    except _ModalityLockConflict as e:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "another mode is currently active — end the existing session first.",
                "held": e.held,
                "requested": e.requested,
            },
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="session not found")
    except Exception as e:
        logger.exception("session_load_failed", session_id=str(session_id))
        raise HTTPException(status_code=500, detail=str(e))
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    # Defense-in-depth: verify the loaded session actually belongs to the caller's org/user
    if (
        str(session.get("user_id")) != str(current.user.id)
        or str(session.get("organization_id")) != str(current.organization_id)
    ):
        raise HTTPException(status_code=404, detail="session not found")

    return StreamingResponse(
        _sse_stream(
            supabase_client=supabase,
            anthropic_client=anthropic,
            session_id=str(session_id),
            user_message=payload.message,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


async def _sse_opening_stream(
    supabase_client,
    anthropic_client,
    session_id: str,
) -> AsyncIterator[str]:
    try:
        async for kind, payload in run_text_opening(
            supabase_client=supabase_client,
            anthropic_client=anthropic_client,
            model=ANTHROPIC_MODEL,
            session_id=session_id,
        ):
            if kind == "text":
                yield _sse_event("text", payload)
            elif kind == "done":
                yield _sse_event("done", payload)
    except ModalityConflictError as e:
        yield _sse_event("error", {"message": str(e), "code": "modality_conflict"})
    except Exception as e:
        logger.exception("text_opening_failed", session_id=session_id)
        yield _sse_event("error", {"message": str(e)[:300], "code": "internal_error"})


@router.post("/{session_id}/text/opening")
async def post_text_opening(
    session_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
    anthropic=Depends(get_anthropic_async_client),
):
    """Stream the agent's proactive opening greeting for a text session.

    Idempotent: run_text_opening no-ops if the session already has turns, so
    the frontend can call this on mount without risking a double greeting.
    Ownership is enforced the same way as the message route.
    """
    from intake_core.persistence import aload_session

    try:
        session = await aload_session(supabase, str(session_id))
    except Exception as e:
        logger.exception("opening_session_load_failed", session_id=str(session_id))
        raise HTTPException(status_code=500, detail=str(e))
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if (
        str(session.get("user_id")) != str(current.user.id)
        or str(session.get("organization_id")) != str(current.organization_id)
    ):
        raise HTTPException(status_code=404, detail="session not found")

    return StreamingResponse(
        _sse_opening_stream(
            supabase_client=supabase,
            anthropic_client=anthropic,
            session_id=str(session_id),
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
