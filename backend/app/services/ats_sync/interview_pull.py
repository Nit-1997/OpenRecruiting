"""Idempotent 'fetch + upsert interviews for one application' — the single write
path shared by the webhook-triggered targeted pull (handlers.py) and the reconcile
worker (interview_reconcile.py). Both call this so they converge on identical rows
(spec §5: same upserts on the same keys → no double-ingest).

The write is one ats_upsert_interview RPC per fetched event, keyed on
(organization_id, ats_interview_event_id). Returns the number of events upserted."""

from __future__ import annotations

from app.api.v2.core.rpc import call_rpc
from app.integrations.ats.core.models import AtsInterview
from app.logging_config import get_logger

logger = get_logger(__name__)


def _to_fields(interview: AtsInterview, provider: str) -> dict:
    return {
        "ats_interview_event_id": interview.event_id,
        "ats_application_id": interview.application_id,
        "ats_schedule_id": interview.schedule_id,
        "ats_interview_id": interview.interview_id,
        "ats_stage_id": interview.stage_id,
        "stage_name": interview.stage_name,
        "interview_title": interview.interview_title,
        "scheduled_start": interview.scheduled_start,
        "scheduled_end": interview.scheduled_end,
        "status": interview.status,
        "interviewers": [w.model_dump() for w in interview.interviewers],
        "meeting_url": interview.meeting_url,
        "feedback_link": interview.feedback_link,
        "has_submitted_feedback": interview.has_submitted_feedback,
        "notetaker_transcript_id": interview.notetaker_transcript_id,
        "provider": provider,
        "raw": interview.model_dump(),
    }


async def pull_interviews_for_application(
    supabase, bundle, org_id: str, application_id: str
) -> int:
    """Fetch all interviews for application_id via the provider's native adapter and
    idempotently upsert each. No-op when the provider has no interviews adapter."""
    interviews_adapter = getattr(bundle, "interviews", None)
    if interviews_adapter is None:
        return 0

    interviews = await interviews_adapter.fetch_interviews(application_id)
    upserted = 0
    for interview in interviews:
        await call_rpc(
            supabase,
            "ats_upsert_interview",
            {
                "p_org": org_id,
                "p_connection": bundle.connection_id,
                "p_fields": _to_fields(interview, bundle.provider),
            },
        )
        upserted += 1
    if upserted:
        logger.info(
            "ats_interviews_upserted",
            extra={
                "event": "ats_interviews_upserted",
                "application_id": application_id,
                "n": upserted,
            },
        )
    return upserted
