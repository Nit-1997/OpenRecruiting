"""
Candidate-round journey mutations (schedule / reschedule / cancel).

Endpoints owned:
  POST /candidate-rounds/{cr_id}/schedule  → schedule_candidate_round
  PUT  /candidate-rounds/{cr_id}/schedule  → reschedule_candidate_round
  POST /candidate-rounds/{cr_id}/cancel    → cancel_candidate_round

Recall.ai is called OUTSIDE the DB transaction (spec orchestration rule):
the RPC persists the schedule first, then the orchestrator creates the bot.
A Recall failure leaves the schedule intact with `bot:null`.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from app.api.v2.core.exceptions import NotFoundError
from app.api.v2.core.rpc import call_rpc
from app.api.v2.schemas.interview import (
    RescheduleInterviewRequest,
    ScheduleInterviewRequest,
)
from app.api.v2.services import recall_orchestrator
from app.logging_config import get_logger, log_operation


logger = get_logger(__name__)


# Match v1 default — assessment access codes expire after this window unless
# explicitly extended.
_ACCESS_CODE_EXPIRATION_DAYS = 3
_ACCESS_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_INSTANCE_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _generate_access_code(length: int = 8) -> str:
    return "".join(secrets.choice(_ACCESS_CODE_ALPHABET) for _ in range(length))


def _hash_access_code(code: str) -> str:
    return hashlib.sha256(code.upper().encode()).hexdigest()


def _generate_instance_id() -> str:
    suffix = "".join(secrets.choice(_INSTANCE_ID_ALPHABET) for _ in range(8))
    return f"inst_{suffix}"


async def load_cr_with_round_for_org(supabase, cr_id: UUID, org_id: str) -> dict:
    """Fetch a candidate_round + its round + verify the org chain.

    Public (no leading underscore) because feedback_service and the routers
    (for the recording-url endpoint) need to call it too.
    """
    result = await (
        supabase.table("candidate_rounds")
        .select(
            "*, rounds(id, assessment_template_id, name, round_number, deleted_at), "
            "candidates(id, name, email, requisition_id, deleted_at, "
            "requisitions(id, organization_id, status, deleted_at))"
        )
        .eq("id", str(cr_id))
        .single()
        .execute_async()
    )
    if not result.data:
        raise NotFoundError("Candidate round not found")

    cand = result.data.get("candidates") or {}
    req = cand.get("requisitions") or {}
    rnd = result.data.get("rounds") or {}

    if (
        req.get("organization_id") != org_id
        or req.get("deleted_at") is not None
        or cand.get("deleted_at") is not None
        or rnd.get("deleted_at") is not None
    ):
        raise NotFoundError("Candidate round not found")
    return result.data


def _build_assessment_instance_payload(
    template_id: str,
    candidate_name: Optional[str],
    candidate_email: Optional[str],
) -> dict:
    access_code = _generate_access_code(8)
    expiry = datetime.now(timezone.utc) + timedelta(days=_ACCESS_CODE_EXPIRATION_DAYS)
    return {
        "id": _generate_instance_id(),
        "template_id": str(template_id),
        "candidate_email": candidate_email,
        "candidate_name": candidate_name,
        "access_code": access_code,
        "access_code_hash": _hash_access_code(access_code),
        "access_code_expires_at": expiry.isoformat(),
        "status": "pending",
        "expires_at": expiry.isoformat(),
    }


# ---------------------------------------------------------------------------
# POST /candidate-rounds/{cr_id}/schedule
# ---------------------------------------------------------------------------


async def schedule_candidate_round(
    supabase,
    org_id: str,
    cr_id: UUID,
    body: ScheduleInterviewRequest,
) -> dict:
    """First-time schedule (or re-schedule of a previously cancelled CR).

    Returns: { candidate_round, assessment_instance | null, bot | null }.
    """
    async with log_operation(
        logger,
        "v2.schedule_candidate_round",
        cr_id=str(cr_id),
        has_meeting_url=bool(body.meeting_url),
    ):
        # Pre-flight: fail fast on cross-org and learn whether the round
        # has an assessment_template_id to inline-insert an instance row.
        cr = await load_cr_with_round_for_org(supabase, cr_id, org_id)
        rnd = cr.get("rounds") or {}
        template_id = rnd.get("assessment_template_id")

        instance_payload: Optional[dict] = None
        if template_id:
            cand = cr.get("candidates") or {}
            instance_payload = _build_assessment_instance_payload(
                template_id=template_id,
                candidate_name=cand.get("name"),
                candidate_email=cand.get("email"),
            )

        data = await call_rpc(
            supabase,
            "schedule_candidate_round",
            {
                "p_cr_id": str(cr_id),
                "p_scheduled_at": body.scheduled_at.isoformat(),
                "p_interviewer_email": (
                    str(body.interviewer_email) if body.interviewer_email else None
                ),
                "p_interviewer_name": body.interviewer_name,
                "p_meeting_url": str(body.meeting_url) if body.meeting_url else None,
                "p_scheduling_timezone": body.scheduling_timezone,
                "p_assessment_instance": instance_payload,
                "p_org_id": org_id,
            },
        )
        payload = data or {}
        candidate_name = payload.get("candidate_name") or ""
        updated_cr = payload.get("candidate_round")
        instance = payload.get("assessment_instance")

        # Create Recall bot AFTER the DB transaction commits. Failures
        # here do not roll back; we return bot:null and the recruiter
        # can retry.
        bot_info: Optional[dict] = None
        if body.meeting_url:
            bot_info = await recall_orchestrator.create_recall_bot_for_cr(
                cr_id=cr_id,
                candidate_name=candidate_name,
                meeting_url=str(body.meeting_url),
                scheduled_at=body.scheduled_at,
            )

        return {
            "candidate_round": updated_cr,
            "assessment_instance": instance,
            "bot": bot_info,
        }


# ---------------------------------------------------------------------------
# PUT /candidate-rounds/{cr_id}/schedule
# ---------------------------------------------------------------------------


async def reschedule_candidate_round(
    supabase,
    org_id: str,
    cr_id: UUID,
    body: RescheduleInterviewRequest,
) -> dict:
    """Requires current status='scheduled'.

    If meeting_url changes (or is explicitly cleared via clear_meeting_url),
    the existing Recall bot is cancelled and a new one created if there is a
    new url. If only date/email changes the bot is left alone — Recall does
    not expose a clean 'update scheduled bot time' API and v1 does not push
    new times either; we mirror v1.

    Assessment instance lifecycle: untouched on reschedule.
    """
    data = await call_rpc(
        supabase,
        "reschedule_candidate_round",
        {
            "p_cr_id": str(cr_id),
            "p_scheduled_at": body.scheduled_at.isoformat() if body.scheduled_at else None,
            "p_interviewer_email": str(body.interviewer_email) if body.interviewer_email else None,
            "p_interviewer_name": body.interviewer_name,
            "p_meeting_url": str(body.meeting_url) if body.meeting_url else None,
            "p_scheduling_timezone": body.scheduling_timezone,
            "p_clear_meeting_url": body.clear_meeting_url,
            "p_org_id": org_id,
        },
    )
    payload = data or {}
    updated_cr = payload.get("candidate_round") or {}
    prev_meeting_url = payload.get("prev_meeting_url")
    candidate_name = payload.get("candidate_name") or ""

    new_meeting_url = updated_cr.get("meeting_url")
    new_scheduled_at_raw = updated_cr.get("scheduled_at")

    url_changed = (new_meeting_url or None) != (prev_meeting_url or None)

    bot_info: Optional[dict] = None
    if url_changed:
        await recall_orchestrator.cancel_recall_bot_for_cr(cr_id)
        if new_meeting_url:
            try:
                scheduled_dt = datetime.fromisoformat(
                    str(new_scheduled_at_raw).replace("Z", "+00:00")
                )
            except (TypeError, ValueError):
                scheduled_dt = body.scheduled_at or datetime.now(timezone.utc)
            bot_info = await recall_orchestrator.create_recall_bot_for_cr(
                cr_id=cr_id,
                candidate_name=candidate_name,
                meeting_url=new_meeting_url,
                scheduled_at=scheduled_dt,
            )

    return {
        "candidate_round": updated_cr,
        "bot": bot_info,
    }


# ---------------------------------------------------------------------------
# POST /candidate-rounds/{cr_id}/cancel
# ---------------------------------------------------------------------------


async def cancel_candidate_round(supabase, org_id: str, cr_id: UUID) -> dict:
    """Cancel a candidate round; refused if status='completed' (terminal).
    Idempotent if already cancelled."""
    async with log_operation(
        logger,
        "v2.cancel_candidate_round",
        cr_id=str(cr_id),
    ):
        data = await call_rpc(
            supabase,
            "cancel_candidate_round",
            {
                "p_cr_id": str(cr_id),
                "p_org_id": org_id,
            },
        )
        payload = data or {}
        await recall_orchestrator.cancel_recall_bot_for_cr(cr_id)
        return {"candidate_round": payload.get("candidate_round")}
