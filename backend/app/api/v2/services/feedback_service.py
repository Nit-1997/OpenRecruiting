"""
Interviewer-feedback endpoints (human-submitted + notification + Lambda
reprocess).

Endpoints owned:
  POST /candidate-rounds/{cr_id}/feedback           → submit_feedback
  POST /candidate-rounds/{cr_id}/request-feedback   → request_feedback
  POST /candidate-rounds/{cr_id}/reprocess          → reprocess_feedback
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from app.api.v2.core.exceptions import (
    ConflictError,
    NotImplementedFeatureError,
    UpstreamServiceError,
    ValidationError,
)
from app.api.v2.core.rpc import call_rpc
from app.api.v2.schemas.feedback import (
    ReprocessRequest,
    RequestFeedbackRequest,
    SubmitFeedbackRequest,
)
from app.api.v2.services.journey_service import load_cr_with_round_for_org
from app.logging_config import get_logger, log_operation


logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# POST /candidate-rounds/{cr_id}/feedback
# ---------------------------------------------------------------------------


async def submit_feedback(
    supabase, org_id: str, cr_id: UUID, body: SubmitFeedbackRequest
) -> dict:
    """Human-submitted feedback path (NOT the AI Lambda).

    Transitions the CR to status='completed' and writes the scorecard.
    `body.scorecard` is accepted for forward-compat but is not persisted —
    no DB column.
    """
    entries_payload = [
        {
            "feedback_question_id": str(e.feedback_question_id),
            "feedback_text": e.feedback_text,
            "evidence_status": e.evidence_status,
            "evidence": e.evidence or [],
        }
        for e in body.entries
    ]

    data = await call_rpc(
        supabase,
        "submit_human_feedback",
        {
            "p_cr_id": str(cr_id),
            "p_entries": entries_payload,
            "p_rating": body.rating,
            "p_summary": body.summary,
            "p_org_id": org_id,
        },
    )
    payload = data or {}
    return {
        "candidate_round": payload.get("candidate_round"),
        "entries": payload.get("entries") or [],
    }


# ---------------------------------------------------------------------------
# POST /candidate-rounds/{cr_id}/request-feedback
# ---------------------------------------------------------------------------


async def request_feedback(
    supabase, org_id: str, cr_id: UUID, body: RequestFeedbackRequest
) -> dict:
    """Notification path — does NOT trigger the AI Lambda.

    Today only `channel='email'` is wired through
    FeedbackNotificationService.send_capture_request_to_interviewer.
    Slack/both surface 501 for the slack portion.
    """
    await load_cr_with_round_for_org(supabase, cr_id, org_id)

    # Persist the interviewer email AND name so the recruiter's pick sticks and
    # the packet shows the name (the packet RPC reads candidate_rounds.interviewer_name,
    # not only the profiles lookup). Only overwrite the name when one was provided
    # so a name-less request doesn't wipe an existing name.
    cr_update: dict = {
        "interviewer_email": str(body.interviewer_email),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if body.interviewer_name and body.interviewer_name.strip():
        cr_update["interviewer_name"] = body.interviewer_name.strip()
    await (
        supabase.table("candidate_rounds")
        .update(cr_update)
        .eq("id", str(cr_id))
        .execute_async()
    )

    if body.channel == "slack":
        raise NotImplementedFeatureError(
            "Slack channel for /request-feedback is not implemented yet"
        )

    from app.services.feedback_notification_service import (
        get_feedback_notification_service,
    )

    notification_service = get_feedback_notification_service()
    cr_context = await notification_service._get_candidate_round_context(str(cr_id))
    if not cr_context:
        raise UpstreamServiceError(
            "Failed to build candidate round context for notification",
            status_code=500,
        )

    interviewer_name = (
        body.interviewer_name or str(body.interviewer_email).split("@")[0]
    )
    interviewer_tuple = (str(body.interviewer_email), interviewer_name)

    try:
        result = await notification_service.send_capture_request_to_interviewer(
            interviewer_tuple, cr_context, str(cr_id)
        )
    except Exception as e:
        logger.error(
            "v2 request-feedback: notification failed cr_id=%s err=%s",
            str(cr_id), str(e),
        )
        raise UpstreamServiceError(
            "Failed to send feedback request",
            status_code=500,
        )

    return {
        "sent": bool(result.get("sent")),
        "request_id": result.get("message_id"),
        "channel": body.channel,
    }


# ---------------------------------------------------------------------------
# POST /candidate-rounds/{cr_id}/reprocess
# ---------------------------------------------------------------------------


async def reprocess_feedback(
    supabase, org_id: str, cr_id: UUID, body: ReprocessRequest
) -> dict:
    """Trigger the feedback Lambda to (re)generate AI feedback.

    Precondition: candidate_round.status == 'completed'. Otherwise 400.
    Concurrency: cr.processing_status != 'processing' unless force=true.

    Force=true bypasses the in-flight guard inside FeedbackJobService
    (skip_prereq_check=True) — see CLAUDE.md "Lambda Code — Mandatory Rules"
    (May 2026 round 1ecc51c1 incident). The Lambda's writes are idempotent
    on candidate_round_id, so a concurrent retry converges on the same final
    state. ADDING ANY NEW force=true CALLER REQUIRES FRESH IDEMPOTENCY
    ANALYSIS per CLAUDE.md.
    """
    async with log_operation(
        logger,
        "v2.reprocess_feedback",
        cr_id=str(cr_id),
        force=bool(body.force),
    ):
        cr = await load_cr_with_round_for_org(supabase, cr_id, org_id)

        if cr.get("status") != "completed":
            raise ValidationError("Reprocess requires a completed round")

        if cr.get("processing_status") == "processing" and not body.force:
            raise ConflictError(
                "ALREADY_PROCESSING",
                (
                    "Feedback processing is already in flight. "
                    "Pass force=true to retry anyway (the Lambda is idempotent)."
                ),
            )

        from app.services.feedback_job_service import get_feedback_job_service

        feedback_service = get_feedback_job_service()
        triggered_at = datetime.now(timezone.utc)
        try:
            await feedback_service.trigger_feedback_processing(
                str(cr_id),
                skip_prereq_check=body.force,
            )
        except Exception as e:
            logger.error(
                "v2 reprocess: feedback Lambda trigger failed cr_id=%s err=%s",
                str(cr_id), str(e),
            )
            raise UpstreamServiceError(
                "Failed to trigger feedback reprocessing",
                status_code=500,
            )

        return {
            "candidate_round_id": str(cr_id),
            "processing_status": "processing",
            "triggered_at": triggered_at.isoformat(),
        }
