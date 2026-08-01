"""Internal endpoint called by voice-agent when a feedback voice session ends.

The voice agent owns the transcript write and the status transition. It calls
here so that the existing feedback Lambda trigger logic stays in backend
(single place that knows the Lambda ARN, single place that owns prereq checks).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.api.v2.core.dependencies import verify_internal_secret
from app.logging_config import get_logger
from app.models.feedback import VoiceCompleteRequest, VoiceCompleteResponse
from app.services.feedback_job_service import get_feedback_job_service
from app.services.supabase import get_supabase_admin_client

logger = get_logger(__name__)
router = APIRouter(prefix="/internal", dependencies=[Depends(verify_internal_secret)])


@router.post("/feedback/voice-complete", response_model=VoiceCompleteResponse)
async def voice_complete(body: VoiceCompleteRequest):
    """Voice agent reports the end of a feedback session.

    The update is constrained by both candidate_round_id AND
    voice_session_token AND a non-terminal status. A stale voice-agent task
    (e.g., one that the user superseded with a redo) finds zero rows to
    update and is rejected — its transcript cannot overwrite the in-flight
    session's row. On terminal write we also null the token so the same
    URL cannot be replayed.
    """
    supabase = get_supabase_admin_client()
    now = datetime.now(timezone.utc).isoformat()

    if body.status == "completed":
        update_payload = {
            "scorecard_transcript": body.transcript,
            "feedback_voice_session_status": "completed",
            "feedback_voice_session_token": None,
            "feedback_voice_session_error": None,
            "updated_at": now,
        }
    else:
        update_payload = {
            "feedback_voice_session_status": "error",
            "feedback_voice_session_token": None,
            "feedback_voice_session_error": (body.error_reason or "unknown")[:500],
            "updated_at": now,
        }

    update_result = (
        await supabase.table("candidate_rounds")
        .update(update_payload)
        .eq("id", body.candidate_round_id)
        .eq("feedback_voice_session_token", body.voice_session_token)
        .in_("feedback_voice_session_status", ["pending", "active"])
        .execute_async()
    )

    affected = update_result.data or []
    if not affected:
        logger.warning(
            f"voice-complete ignored as stale: candidate_round={body.candidate_round_id} "
            f"status={body.status} token={body.voice_session_token[:8]}..."
        )
        return VoiceCompleteResponse(
            success=False, processing_status=None, reason="stale_or_already_terminal"
        )

    if body.status != "completed":
        logger.warning(
            f"Voice feedback failed for candidate_round {body.candidate_round_id}: "
            f"{body.error_reason}"
        )
        return VoiceCompleteResponse(success=True, processing_status=None)

    feedback_service = get_feedback_job_service()
    try:
        result = await feedback_service.trigger_feedback_processing(
            body.candidate_round_id, skip_prereq_check=True
        )
        processing_status = (
            "processing" if result.get("status") == "accepted" else "pending"
        )
    except Exception as e:
        logger.error(
            f"Failed to trigger feedback Lambda for {body.candidate_round_id}: {e}"
        )
        processing_status = "pending"

    logger.info(
        f"Voice feedback completed for candidate_round {body.candidate_round_id} "
        f"(transcript={len(body.transcript)} chars, lambda={processing_status})"
    )
    return VoiceCompleteResponse(success=True, processing_status=processing_status)
