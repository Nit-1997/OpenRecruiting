"""
Recall.ai bot lifecycle helpers for v2 candidate-round mutations.

These helpers live OUTSIDE any DB transaction — the journey-service RPCs
persist the candidate_round state first, then this module is asked to
(de)provision the bot. A Recall failure does NOT roll back the schedule;
the caller surfaces `bot=null` and the recruiter can retry by editing
meeting_url.

Spec orchestration rule: external-side-effect, post-commit; idempotent
where feasible; failures logged and swallowed for cancel.

Test surface: tests/api/v2/test_journey_mutations.py monkey-patches
`create_recall_bot_for_cr` and `cancel_recall_bot_for_cr` directly on this
module (see `app.api.v2.services.recall_orchestrator`).
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import HTTPException

from app.logging_config import get_logger
from app.services.supabase import get_supabase_admin_client


logger = get_logger(__name__)


async def create_recall_bot_for_cr(
    cr_id: UUID,
    candidate_name: str,
    meeting_url: str,
    scheduled_at: datetime,
) -> Optional[dict]:
    """Create a Recall bot for a candidate round, outside any DB transaction.

    Returns the bot info dict or None on failure (logs the warning).
    Mirrors the v1 path (schedule_or_replace_recall_bot) but is decoupled
    from the v2 schedule RPC.

    HTTPException (e.g. the scheduling-lock 409 raised by
    schedule_or_replace_recall_bot) is re-raised — the recruiter must see
    a lock. Any other exception is logged and swallowed.
    """
    from app.services.recall_service import schedule_or_replace_recall_bot

    try:
        result = await schedule_or_replace_recall_bot(
            candidate_round_id=str(cr_id),
            meeting_url=meeting_url,
            scheduled_at=scheduled_at,
            candidate_name=candidate_name,
        )
        warning = result.get("recall_warning")
        if warning:
            logger.warning(
                "v2 schedule: Recall bot creation warning cr_id=%s warning=%s",
                str(cr_id), warning,
            )
            return None

        supabase = get_supabase_admin_client()
        bot_result = await (
            supabase.table("recall_bots")
            .select("id, recall_bot_id, status, meeting_url, scheduled_at")
            .eq("candidate_round_id", str(cr_id))
            .order("created_at", desc=True)
            .limit(1)
            .execute_async()
        )
        if bot_result.data:
            row = (
                bot_result.data[0]
                if isinstance(bot_result.data, list)
                else bot_result.data
            )
            return {
                "id": row.get("id"),
                "recall_bot_id": row.get("recall_bot_id"),
                "status": row.get("status"),
                "meeting_url": row.get("meeting_url"),
                "scheduled_at": row.get("scheduled_at"),
            }
        return None
    except HTTPException:
        # schedule_or_replace_recall_bot raises 409 for the scheduling lock.
        # Bubble it up — the recruiter must see it.
        raise
    except Exception as e:
        logger.warning(
            "v2 schedule: Recall bot creation failed cr_id=%s error=%s",
            str(cr_id), str(e),
        )
        return None


async def cancel_recall_bot_for_cr(cr_id: UUID) -> None:
    """Find and cancel any active Recall bot for this candidate_round.

    Mirrors the cleanup half of schedule_or_replace_recall_bot but stops
    short of creating a new bot. Errors are logged, never raised — cancel
    must not block the DB-side cancel handler from returning success.
    """
    from app.services.recall_service import (
        ACTIVE_BOT_STATUSES,
        get_recall_service,
    )

    supabase = get_supabase_admin_client()
    existing = await (
        supabase.table("recall_bots")
        .select("id, recall_bot_id, status")
        .eq("candidate_round_id", str(cr_id))
        .in_("status", ACTIVE_BOT_STATUSES)
        .execute_async()
    )
    if not existing.data:
        return

    recall_service = get_recall_service()
    try:
        for bot in existing.data:
            bot_status = bot.get("status", "created")
            api_cancel_ok = True
            try:
                if bot_status in ("joining", "in_waiting_room"):
                    await recall_service.remove_bot_from_call(bot["recall_bot_id"])
                await recall_service.delete_bot(bot["recall_bot_id"])
            except Exception as e:
                api_cancel_ok = False
                # Loud log — the bot will keep joining the meeting until
                # someone re-runs cancel or the meeting ends. Without this
                # signal the DB would say "cancelled" while Recall would
                # still send the bot.
                logger.error(
                    "v2 cancel: Recall API cancel FAILED bot_id=%s cr_id=%s status=%s err=%s "
                    "(DB row left in prior status; recall_bot will continue until manual retry)",
                    bot["recall_bot_id"], str(cr_id), bot_status, str(e),
                )

            # Only flip the DB row to 'cancelled' when the Recall API
            # actually accepted the cancel. Otherwise the DB state would
            # diverge from Recall's view — the bot would keep dialing in
            # while we claim it's gone.
            if api_cancel_ok:
                await (
                    supabase.table("recall_bots")
                    .update({"status": "cancelled"})
                    .eq("id", bot["id"])
                    .execute_async()
                )
    finally:
        await recall_service.close()
