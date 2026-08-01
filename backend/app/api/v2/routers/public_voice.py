"""Public voice-session status — polled by the Recall-bot camera page
(voice-frontend, served at localhost:8011/{token}) so it knows when
to connect the Pipecat voice agent into the meeting.

No auth: the only credential is the opaque voice_session_token minted at bot
creation (recall_service). Returns ONLY the status string — no PII, no other
columns. Replaces the retired v1 GET /api/v1/public/voice/status/{token}, whose
removal (v1 decommission, 2026-06-01) left the camera page polling a 404 and
stuck on its dormant view: the bot rendered in the meeting but the agent never
went live (voice_session_status stuck at 'activating').
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.logging_config import get_logger
from app.services.supabase import get_supabase_admin_client

logger = get_logger(__name__)

router = APIRouter(prefix="/public/voice", tags=["v2/public-voice"])


@router.get("/status/{token}")
async def get_voice_session_status(token: str) -> dict:
    """Return {"status": recall_bots.voice_session_status} for the bot holding
    this voice_session_token. The camera page connects the agent once status is
    'activating'/'active'. An unknown (or malformed) token returns 'dormant' so
    the page keeps polling harmlessly rather than erroring."""
    # voice_session_token is a uuid column — a non-uuid token can't match any bot
    # and would raise 22P02 on the cast (a 500). Short-circuit to dormant.
    try:
        UUID(token)
    except (ValueError, AttributeError, TypeError):
        return {"status": "dormant"}

    supabase = get_supabase_admin_client()
    result = await (
        supabase.table("recall_bots")
        .select("voice_session_status")
        .eq("voice_session_token", token)
        .execute_async()
    )
    rows = result.data or []
    status = (rows[0].get("voice_session_status") if rows else None) or "dormant"
    return {"status": status}
