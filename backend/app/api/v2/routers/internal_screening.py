"""Internal endpoint called by voice-agent when a screening voice call ends.

Mirrors `internal_feedback.py`. The voice agent reports the end of a screening
session with a speaker-attributed transcript STRING. This route:

  1. CAS-updates `candidate_rounds.screening_voice_session_status` -> completed
     (or error), scoped by id + token + a non-terminal status, and nulls the
     token (replay protection). A stale/superseded callback finds zero rows and
     is rejected — its transcript cannot clobber the in-flight session's row.
  2. On completion: parses the speaker-attributed string into
     `[{"speaker","text"}]` segments and upserts them into `transcripts.segments`
     for this candidate_round (the EVIDENCE the feedback Lambda reads via
     candidate_round_id — a UNIQUE FK on transcripts).
  3. Schedules `ScreeningFeedbackService.generate_and_dispatch` OFF the request
     path (BackgroundTasks) so the voice agent's callback returns fast. That
     service authors the interviewer-style assessment and triggers the existing
     feedback Lambda.

Async invariant: all DB IO goes through the custom async Supabase client
(execute_async); never the sync `.execute` twin.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field

from app.api.v2.core.dependencies import verify_internal_secret
from app.logging_config import get_logger
from app.services.screening_feedback_service import get_screening_feedback_service
from app.services.supabase import get_supabase_admin_client

logger = get_logger(__name__)
router = APIRouter(prefix="/internal", dependencies=[Depends(verify_internal_secret)])

# Statuses from which a voice-complete callback may transition. Mirrors the
# screening /start-voice mint, which sets 'pending'; the agent may flip to
# 'active' while running.
_NON_TERMINAL_STATUSES = ["pending", "active"]


class ScreeningVoiceCompleteRequest(BaseModel):
    candidate_round_id: str
    voice_session_token: str
    transcript: str = ""
    status: str = Field(..., pattern=r"^(completed|error)$")
    error_reason: Optional[str] = None


class ScreeningVoiceCompleteResponse(BaseModel):
    success: bool
    reason: Optional[str] = None


def _parse_transcript_segments(transcript: str) -> list[dict]:
    """Parse a speaker-attributed, blank-line-separated transcript string into
    simple `{"speaker","text"}` segments — the shape the feedback Lambda's
    get_transcript_data / _extract_segment_speaker consumes.

    Each turn looks like `"Scout Interviewer: ...\\n\\nCandidate: ..."`. A turn
    with no `"Speaker:"` prefix is kept as text with an empty speaker so no
    content is silently dropped.
    """
    segments: list[dict] = []
    for block in (transcript or "").split("\n\n"):
        chunk = block.strip()
        if not chunk:
            continue
        speaker = ""
        text = chunk
        if ":" in chunk:
            head, tail = chunk.split(":", 1)
            # Treat as a speaker label only if it is short and single-line —
            # avoids misreading a colon inside the answer body as a label.
            if "\n" not in head and len(head) <= 40:
                speaker = head.strip()
                text = tail.strip()
        if not text:
            continue
        segments.append({"speaker": speaker, "text": text})
    return segments


@router.post("/screening/voice-complete", response_model=ScreeningVoiceCompleteResponse)
async def screening_voice_complete(
    body: ScreeningVoiceCompleteRequest, background_tasks: BackgroundTasks
):
    """Voice agent reports the end of a screening session.

    The CAS update is constrained by candidate_round_id AND
    screening_voice_session_token AND a non-terminal status. A stale/superseded
    callback finds zero rows, is rejected, and does NOT proceed. On the terminal
    write the token is nulled so the same URL cannot be replayed.
    """
    supabase = get_supabase_admin_client()
    now = datetime.now(timezone.utc).isoformat()

    if body.status == "completed":
        update_payload = {
            "screening_voice_session_status": "completed",
            "screening_voice_session_token": None,
            "screening_voice_session_error": None,
            "updated_at": now,
        }
    else:
        update_payload = {
            "screening_voice_session_status": "error",
            "screening_voice_session_token": None,
            "screening_voice_session_error": (body.error_reason or "unknown")[:500],
            "updated_at": now,
        }

    update_result = await (
        supabase.table("candidate_rounds")
        .update(update_payload)
        .eq("id", body.candidate_round_id)
        .eq("screening_voice_session_token", body.voice_session_token)
        .in_("screening_voice_session_status", _NON_TERMINAL_STATUSES)
        .execute_async()
    )

    if not (update_result.data or []):
        logger.warning(
            "screening.voice_complete.stale",
            extra={
                "event": "screening.voice_complete",
                "status": "stale",
                "candidate_round_id": body.candidate_round_id,
                "reported_status": body.status,
            },
        )
        return ScreeningVoiceCompleteResponse(
            success=False, reason="stale_or_superseded"
        )

    if body.status != "completed":
        logger.warning(
            "screening.voice_complete.error",
            extra={
                "event": "screening.voice_complete",
                "status": "error",
                "candidate_round_id": body.candidate_round_id,
                "error": (body.error_reason or "unknown")[:200],
            },
        )
        return ScreeningVoiceCompleteResponse(success=True)

    # Persist the interview transcript as EVIDENCE. transcripts.candidate_round_id
    # is a UNIQUE FK -> upsert on that conflict is idempotent for a redo/retry.
    segments = _parse_transcript_segments(body.transcript)
    await (
        supabase.table("transcripts")
        .upsert(
            {
                "candidate_round_id": body.candidate_round_id,
                "segments": segments,
                "full_text": body.transcript,
                "provider": "ai_screening",
                "processed_at": now,
            },
            on_conflict="candidate_round_id",
        )
        .execute_async()
    )

    # Author the assessment + trigger the existing feedback Lambda OFF the request
    # path so the voice agent's callback returns fast.
    feedback_service = get_screening_feedback_service()
    background_tasks.add_task(
        feedback_service.generate_and_dispatch, body.candidate_round_id
    )

    logger.info(
        "screening.voice_complete.completed",
        extra={
            "event": "screening.voice_complete",
            "status": "completed",
            "candidate_round_id": body.candidate_round_id,
            "segments": len(segments),
            "transcript_chars": len(body.transcript),
        },
    )
    return ScreeningVoiceCompleteResponse(success=True)
