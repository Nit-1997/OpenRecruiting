"""
Post-call recording fetch + Lambda trigger.

Runs as a FastAPI BackgroundTask once `bot.status_change → done`. Pulls
recording / transcript / participants URLs from Recall, persists them,
fills in interviewer_email if it can be detected unambiguously, and then
`_decide_feedback_path` routes to one of three terminal outcomes:

  1. Candidate no-show (end-state `is_no_show`) → skip the Lambda,
     complete the round here, and send the "please add feedback" emails.
  2. Meaningful interviewer feedback captured during the call → trigger
     the Lambda directly (with `skip_prereq_check=True`); the Lambda
     completes the round.
  3. Otherwise → complete the round here + send the post-interview
     "please add feedback" emails.

Intake-call path (no candidate_round_id, only requisition_id) is
deliberately NOT ported — that's owned by v1's intake_job_service.
v2-scheduled interview bots always have a candidate_round_id.

Single responsibility: orchestration. Sub-decisions delegate to
`partial_feedback` and `interviewer_detection`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.logging_config import correlation_id_var, get_logger, log_operation
from app.services.feedback_job_service import (
    FeedbackJobServiceError,
    get_feedback_job_service,
)
from app.services.recall_service import get_recall_service
from app.services.supabase import get_async_http_client, get_supabase_admin_client
from app.services.recall_webhook import end_state, partial_feedback
from app.services.recall_webhook.interviewer_detection import (
    detect_interviewer_emails,
)


logger = get_logger(__name__)


async def fetch_and_store_recording(
    recall_bot_id: str,
    db_record_id: str,
    candidate_round_id: Optional[str],
    requisition_id: Optional[str] = None,
) -> None:
    """Background task: pull recording artefacts, persist, decide on
    feedback trigger.

    Signature mirrors v1's `fetch_and_store_recording` so the call sites
    can move 1:1.
    """
    async with log_operation(
        logger,
        "v2.fetch_and_store_recording",
        recall_bot_id=recall_bot_id,
        candidate_round_id=str(candidate_round_id or ""),
    ):
        supabase = get_supabase_admin_client()
        recall_service = get_recall_service()
        try:
            recording_data = await recall_service.get_recording_urls(recall_bot_id)
            if not recording_data:
                # Recall says bot is done but the recording shortcut
                # returned nothing. Mark the row done and stop — there's
                # no transcript to process.
                await supabase.table("recall_bots")\
                    .update({"status": "done"})\
                    .eq("id", db_record_id)\
                    .execute_async()
                return

            participants_data = await _fetch_participants(recording_data)
            await _persist_recording_metadata(
                supabase, db_record_id, recording_data, participants_data,
            )

            if not candidate_round_id:
                # Detection-only / intake / orphan bots don't get the
                # Lambda branch in v2. v1's auto-join calendar repair
                # (`_materialize_missing_detection_round`) stays in v1.
                logger.info(
                    f"recording: no candidate_round_id for bot={recall_bot_id} — stopping"
                )
                return

            transcript_data = await _fetch_transcript(recording_data)
            _normalise_bot_speaker(transcript_data)
            await _upsert_transcript(
                supabase, candidate_round_id, recording_data,
                transcript_data, participants_data,
            )
            await _fill_interviewer_email_if_missing(
                supabase, candidate_round_id, db_record_id,
            )
            await _decide_feedback_path(
                supabase, candidate_round_id, db_record_id, transcript_data,
            )
        except Exception as e:
            logger.error(
                f"recording: fatal error bot={recall_bot_id}: {e}",
                exc_info=True,
            )
        finally:
            await recall_service.close()


# ---------------------------------------------------------------------------
# private helpers (one concern per function)
# ---------------------------------------------------------------------------


async def _fetch_participants(recording_data: dict) -> Optional[list[dict]]:
    """Fetch the participants JSON if Recall gave us a download URL.
    Best-effort — failure here doesn't block the rest of the pipeline."""
    url = recording_data.get("participants_download_url")
    if not url:
        return None
    try:
        client = get_async_http_client()
        resp = await client.get(url, timeout=60.0)
        if resp.status_code != 200:
            logger.warning(f"recording: participants fetch non-200 status={resp.status_code}")
            return None
        data = resp.json()
        if isinstance(data, list):
            return data
        return None
    except Exception as e:
        logger.warning(f"recording: participants fetch failed: {e}")
        return None


async def _persist_recording_metadata(
    supabase,
    db_record_id: str,
    recording_data: dict,
    participants_data: Optional[list[dict]],
) -> None:
    """Write recording_url / transcript_url / duration / participants to
    `recall_bots` and flip status to done."""
    await supabase.table("recall_bots")\
        .update({
            "status": "done",
            "recording_url": recording_data.get("video_url"),
            "recording_duration_seconds": recording_data.get("video_duration"),
            "transcript_url": recording_data.get("transcript_url"),
            "transcript_ready": bool(recording_data.get("transcript_url")),
            "participants": participants_data or recording_data.get("participants"),
        })\
        .eq("id", db_record_id)\
        .execute_async()


async def _fetch_transcript(recording_data: dict) -> Optional[list[dict]]:
    """Pull the transcript JSON from Recall's S3 link. Best-effort."""
    url = recording_data.get("transcript_url")
    if not url:
        return None
    try:
        client = get_async_http_client()
        resp = await client.get(url, timeout=60.0)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data if isinstance(data, list) else None
    except Exception as e:
        logger.warning(f"recording: transcript fetch failed: {e}")
        return None


def _normalise_bot_speaker(transcript_data: Optional[list[dict]]) -> None:
    """Recall sometimes omits a participant.name for the bot's own
    utterances — patch it to "OpenRecruiting" so the feedback Lambda's bot
    exclusion logic catches them."""
    if not transcript_data:
        return
    for segment in transcript_data:
        if not isinstance(segment, dict):
            continue
        p = segment.get("participant")
        if isinstance(p, dict) and not p.get("name"):
            p["name"] = "OpenRecruiting"


async def _upsert_transcript(
    supabase,
    candidate_round_id: str,
    recording_data: dict,
    transcript_data: Optional[list[dict]],
    participants_data: Optional[list[dict]],
) -> None:
    """Insert-or-update the transcripts row keyed on candidate_round_id."""
    await supabase.table("transcripts")\
        .upsert({
            "candidate_round_id": candidate_round_id,
            "segments": transcript_data,
            "raw_transcript_url": recording_data.get("transcript_url"),
            "duration_seconds": recording_data.get("video_duration"),
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "participant_metadata": participants_data,
        }, on_conflict="candidate_round_id")\
        .execute_async()


async def _fill_interviewer_email_if_missing(
    supabase,
    candidate_round_id: str,
    db_record_id: str,
) -> None:
    """If the recruiter didn't supply interviewer_email at schedule time,
    try to detect it from tracked_participants + candidate name. Skip
    when the field is already set — recruiter intent wins."""
    cr_row = await supabase.table("candidate_rounds")\
        .select("interviewer_email, candidates!inner(name)")\
        .eq("id", candidate_round_id)\
        .single()\
        .execute_async()
    if not cr_row.data:
        return
    if cr_row.data.get("interviewer_email"):
        return

    candidate_name = (cr_row.data.get("candidates") or {}).get("name") or ""
    bot_row = await supabase.table("recall_bots")\
        .select("tracked_participants")\
        .eq("id", db_record_id)\
        .single()\
        .execute_async()
    tracked = (bot_row.data or {}).get("tracked_participants") or []

    detected = detect_interviewer_emails(tracked, candidate_name)
    if detected:
        await supabase.table("candidate_rounds")\
            .update({"interviewer_email": detected[0]})\
            .eq("id", candidate_round_id)\
            .execute_async()
        logger.info(
            f"recording: auto-detected interviewer_email={detected[0]} cr={candidate_round_id}"
        )


async def _decide_feedback_path(
    supabase,
    candidate_round_id: str,
    db_record_id: str,
    transcript_data: Optional[list[dict]],
) -> None:
    """The call has ended. Determine end-state, then ensure the round
    reaches a terminal `completed` state:
      * meaningful interviewer feedback captured (and NOT a no-show) ->
        trigger the Lambda (which sets status='completed');
      * otherwise -> complete the round here + send add-feedback emails.
    """
    bot_row = await supabase.table("recall_bots")\
        .select(
            "feedback_started_at, feedback_status, joined_at, scheduled_at, "
            "candidate_name, detected_candidate_participant_id, tracked_participants"
        )\
        .eq("id", db_record_id)\
        .single()\
        .execute_async()
    rb = bot_row.data or {}

    transcript_row = await supabase.table("transcripts")\
        .select("feedback_transcript, segments")\
        .eq("candidate_round_id", candidate_round_id)\
        .single()\
        .execute_async()
    t = transcript_row.data or {}
    feedback_transcript = t.get("feedback_transcript")
    fallback_segments = t.get("segments") or transcript_data
    feedback_source_present = bool(
        (feedback_transcript and feedback_transcript.strip()) or fallback_segments
    )

    # End-state: ended is forced by the call_ended guardrail; the LLM gives
    # us is_no_show, which routes feedback-vs-no-show.
    verdict = await end_state.evaluate_end_state(
        rb,
        rb.get("tracked_participants") or [],
        end_state.transcript_from_segments(fallback_segments if isinstance(fallback_segments, list) else None),
        trigger="call_ended",
    )

    feedback_status = rb.get("feedback_status")
    feedback_ready = False
    if not verdict.is_no_show and feedback_status in ("completed", "partial", "collecting", "voice_active"):
        start_offset = partial_feedback.feedback_start_offset_seconds(
            rb.get("feedback_started_at"), rb.get("joined_at"),
        )
        candidate_name = (rb.get("candidate_name") or "").strip().lower()
        feedback_ready, source, turns, chars = partial_feedback.is_meaningful_partial_feedback(
            feedback_transcript,
            fallback_segments,
            start_offset,
            candidate_participant_id=rb.get("detected_candidate_participant_id"),
            candidate_names={candidate_name} if candidate_name else set(),
        )
        logger.info(
            f"recording: partial-feedback gate cr={candidate_round_id} "
            f"status={feedback_status} source={source} turns={turns} chars={chars} "
            f"ready={feedback_ready} is_no_show={verdict.is_no_show}"
        )
    else:
        logger.info(
            f"recording: skipping feedback gate cr={candidate_round_id} "
            f"is_no_show={verdict.is_no_show} status={feedback_status} "
            f"end_state={verdict.phase}/{verdict.source}"
        )

    if feedback_ready and feedback_source_present:
        await _trigger_feedback_lambda(supabase, candidate_round_id)  # Lambda completes the round
    else:
        await _complete_round_no_feedback(supabase, candidate_round_id)
        await _send_add_feedback_emails(candidate_round_id)


async def _complete_round_no_feedback(supabase, candidate_round_id: str) -> None:
    """Terminal state for an ended interview with no captured feedback, so
    the recruiter's 'Request feedback' button (gated on status=completed)
    appears. Guarded to only advance an in_progress round."""
    try:
        await supabase.table("candidate_rounds")\
            .update({
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })\
            .eq("id", candidate_round_id)\
            .eq("status", "in_progress")\
            .execute_async()
        logger.info(f"recording: round completed (no captured feedback) cr={candidate_round_id}")
    except Exception as e:
        logger.error(f"recording: complete-round failed cr={candidate_round_id}: {e}", exc_info=True)


async def _trigger_feedback_lambda(supabase, candidate_round_id: str) -> None:
    """Kick the feedback Lambda. `skip_prereq_check=True` because we just
    set up the transcript — the freshness check inside the service would
    otherwise race with our own write. See CLAUDE.md "force=true two-trigger
    races" for the safety story."""
    try:
        result = await get_feedback_job_service().trigger_feedback_processing(
            candidate_round_id, skip_prereq_check=True,
        )
        logger.info(f"recording: Lambda trigger cr={candidate_round_id} result={result}")
        if result.get("status") != "accepted":
            logger.warning(
                f"recording: Lambda not accepted cr={candidate_round_id} reason={result.get('reason')}"
            )
    except FeedbackJobServiceError as e:
        logger.error(f"recording: Lambda trigger failed cr={candidate_round_id}: {e.message}")
    except Exception as e:
        logger.error(
            f"recording: unexpected Lambda trigger failure cr={candidate_round_id}: {e}",
            exc_info=True,
        )
        # Mark the round as failed processing so the recruiter sees a
        # clear signal in the UI instead of "stuck".
        await supabase.table("candidate_rounds")\
            .update({
                "processing_status": "failed",
                "processing_error": f"Lambda trigger failed: {e}",
            })\
            .eq("id", candidate_round_id)\
            .execute_async()


async def _send_add_feedback_emails(candidate_round_id: str) -> None:
    """No live feedback captured — fall back to the email reminder flow."""
    try:
        from app.services.feedback_notification_service import (
            get_feedback_notification_service,
        )
        await get_feedback_notification_service().send_interview_complete_emails(
            candidate_round_id,
        )
        logger.info(
            f"recording: post-interview add-feedback emails sent cr={candidate_round_id}"
        )
    except Exception as e:
        logger.error(
            f"recording: post-interview emails failed cr={candidate_round_id}: {e}",
            exc_info=True,
        )
