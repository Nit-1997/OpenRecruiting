"""
"Scout couldn't join" recruiter notifier.

Fires when Recall's bot status reaches `fatal` or `call_ended` with a
sub_code that means the bot was prevented from entering the meeting
(waiting-room timeout, host denied, rejected, etc.). One email per round,
CAS-guarded so a webhook replay doesn't double-send.

Ported from `backend/v1/app/api/v1/webhooks/recall.py:483-603`.
"""

from __future__ import annotations

from app.logging_config import get_logger
from app.services.email.service import get_email_service
from app.services.supabase import get_supabase_admin_client


logger = get_logger(__name__)


async def notify_bot_not_admitted(recall_bot: dict) -> None:
    """Background task: email the recruiter that the bot couldn't join
    the interview.

    `recall_bot` is the row dict from the moment the webhook fired —
    contains id, candidate_round_id, error_code, etc.
    """
    supabase = get_supabase_admin_client()
    bot_db_id = recall_bot["id"]

    # CAS guard: only the first arrival flips error_code to
    # 'not_admitted_alert_sent'. Subsequent webhook replays see no rows
    # affected and short-circuit. v1 uses the same pattern.
    cas = await supabase.table("recall_bots")\
        .update({"error_code": "not_admitted_alert_sent"})\
        .eq("id", bot_db_id)\
        .neq("error_code", "not_admitted_alert_sent")\
        .execute_async()
    if not cas.data:
        logger.debug(f"not-admitted: already alerted bot={bot_db_id}")
        return

    try:
        await _send_notifications(supabase, recall_bot)
    except Exception as e:
        # Revert the CAS marker so a future retry can attempt delivery
        # again. v1 does the same revert.
        logger.error(f"not-admitted: send failed bot={bot_db_id} err={e}", exc_info=True)
        try:
            await supabase.table("recall_bots")\
                .update({"error_code": "fatal"})\
                .eq("id", bot_db_id)\
                .eq("error_code", "not_admitted_alert_sent")\
                .execute_async()
            logger.info(f"not-admitted: marker reverted bot={bot_db_id} — retry eligible")
        except Exception as revert_err:
            # Revert failed — the CAS marker stays at 'not_admitted_alert_sent'
            # so no automatic retry will fire. Surface it at WARNING instead
            # of swallowing silently, so the stuck round is observable.
            logger.warning(
                f"not-admitted: CAS marker revert failed bot={bot_db_id} "
                f"err={revert_err} — no automatic retry will fire"
            )


# ---------------------------------------------------------------------------
# private helpers
# ---------------------------------------------------------------------------


async def _send_notifications(supabase, recall_bot: dict) -> None:
    cr_id = recall_bot.get("candidate_round_id")
    if not cr_id:
        return

    ctx = await _load_notification_context(supabase, cr_id)
    if not ctx:
        return

    await _send_email(ctx)


async def _load_notification_context(supabase, cr_id: str) -> dict | None:
    """Gather everything the email template needs in one shape.
    Returns None when the candidate_round is gone (deleted between the
    webhook fire and our handler running) — nothing to notify about."""
    cr_row = await supabase.table("candidate_rounds")\
        .select("candidate_id, round_id")\
        .eq("id", cr_id)\
        .execute_async()
    if not cr_row.data:
        return None
    cr = cr_row.data[0]

    round_row = await supabase.table("rounds")\
        .select("name, requisition_id, default_interviewer_emails")\
        .eq("id", cr["round_id"])\
        .execute_async()
    round_info = round_row.data[0] if round_row.data else {}

    req_row = await supabase.table("requisitions")\
        .select("role_title, created_by")\
        .eq("id", round_info.get("requisition_id", ""))\
        .execute_async()
    req = req_row.data[0] if req_row.data else {}

    cand_row = await supabase.table("candidates")\
        .select("name, email")\
        .eq("id", cr["candidate_id"])\
        .execute_async()
    cand = cand_row.data[0] if cand_row.data else {}

    recruiter_id = req.get("created_by")
    if not recruiter_id:
        return None

    profile_row = await supabase.table("profiles")\
        .select("email, full_name")\
        .eq("id", recruiter_id)\
        .execute_async()
    recruiter = profile_row.data[0] if profile_row.data else {}

    interviewer_emails = round_info.get("default_interviewer_emails") or []
    interviewer_email = interviewer_emails[0] if interviewer_emails else ""

    return {
        "cr_id": cr_id,
        "candidate_name": cand.get("name") or "Candidate",
        "role_name": req.get("role_title") or "Role",
        "round_name": round_info.get("name") or "Round",
        "recruiter_id": recruiter_id,
        "recruiter_name": recruiter.get("full_name") or "",
        "recruiter_email": recruiter.get("email") or "",
        "interviewer_email": interviewer_email,
    }


async def _send_email(ctx: dict) -> None:
    """Send the bot_not_admitted.html template to the recruiter."""
    if not ctx["recruiter_email"]:
        logger.warning(f"not-admitted: no recruiter email for cr={ctx['cr_id']}; skipping email")
        return
    email_svc = get_email_service()
    await email_svc.send_templated_email(
        to_email=ctx["recruiter_email"],
        to_name=ctx["recruiter_name"],
        subject=f"{ctx['candidate_name']} – {ctx['role_name']}: Scout couldn't join interview",
        template_name="bot_not_admitted.html",
        context={
            "recruiter_name": ctx["recruiter_name"],
            "candidate_name": ctx["candidate_name"],
            "role_name": ctx["role_name"],
            "round_name": ctx["round_name"],
            "interviewer_email": ctx["interviewer_email"],
        },
    )
    logger.info(
        f"not-admitted: email sent to {ctx['recruiter_email']} cr={ctx['cr_id']}"
    )
