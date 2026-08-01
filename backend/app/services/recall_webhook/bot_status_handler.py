"""
`bot.status_change` event handler — owns candidate_rounds.status
transitions and recall_bots state writes.

State machine (from v1's `webhooks/recall.py:1026-1150`, identical here):

    Recall code              recall_bots.status      candidate_rounds.status
    ────────────────────     ────────────────────    ──────────────────────────
    joining_call             joining                 — (no change)
    in_waiting_room          in_waiting_room         — (no change)
    in_call_not_recording    in_call_not_recording   — (no change)
    in_call_recording        in_call_recording       scheduled → in_progress
                             + joined_at, feedback_status=waiting_for_leave
                             + charge credit (CAS guard)
    call_ended               processing              — (Lambda will mark completed)
                             + left_at, error_code (unless not-admitted)
    done                     done (after recording fetched)
                             → kicks off fetch_and_store_recording BG task
    fatal                    failed                  scheduled (rollback)

Single responsibility: take a parsed event, update DB rows, return
metadata the router needs (e.g. should we enqueue the not-admitted
notifier).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks

from app.logging_config import get_logger, log_operation
from app.services.recall_webhook import utterances
from app.services.recall_webhook.constants import (
    BOT_STATUS_TO_DB,
    is_not_admitted_sub_code,
)


logger = get_logger(__name__)


@dataclass(frozen=True)
class BotStatusOutcome:
    """Structured return for the router. Lets tests assert on what happened
    without scraping log lines."""
    bot_id: str
    db_status: str
    transitioned_cr: bool          # did we flip candidate_rounds.status?
    not_admitted_enqueued: bool    # did we schedule the notifier?
    recording_fetch_enqueued: bool # did we schedule the recording fetch?


async def handle_bot_status_change(
    supabase,
    payload_data: dict,
    background_tasks: BackgroundTasks,
    # Lazy imports below break the otherwise-circular dep:
    #   bot_status -> recording -> feedback_notification_service -> supabase
) -> Optional[BotStatusOutcome]:
    """Process a `bot.status_change` webhook event.

    `payload_data` is the value of the top-level `data` field. Recall puts
    `bot_id` and a nested `status: {code, sub_code, ...}` here.

    Returns `None` when the event was a no-op (unknown bot, malformed
    payload) — the router will surface a `{status: ignored}` response.
    """
    bot_id = payload_data.get("bot_id")
    status_payload = payload_data.get("status") or {}
    status_code = status_payload.get("code")
    sub_code = status_payload.get("sub_code")

    if not bot_id:
        logger.warning("Webhook: bot.status_change missing bot_id; ignoring")
        return None
    if not status_code:
        logger.warning(f"Webhook: bot.status_change missing status code for bot={bot_id}")
        return None

    async with log_operation(
        logger,
        "v2.bot_status_change",
        bot_id=bot_id,
        recall_status=status_code,
        sub_code=sub_code or "",
    ):
        recall_bot = await _load_bot(supabase, bot_id)
        if not recall_bot:
            logger.info(f"Webhook: bot_id={bot_id} not in recall_bots; ignoring")
            return None

        mapped_status = BOT_STATUS_TO_DB.get(status_code, status_code)
        now_iso = datetime.now(timezone.utc).isoformat()

        update_data: dict = {
            "status": mapped_status,
            "last_webhook_at": now_iso,
        }
        # Append to status_history (JSONB array of {status, recall_status,
        # sub_code, timestamp} entries — drives the UI's bot timeline).
        history = recall_bot.get("status_history") or []
        history.append({
            "status": mapped_status,
            "recall_status": status_code,
            "sub_code": sub_code,
            "timestamp": now_iso,
        })
        update_data["status_history"] = history

        transitioned_cr = False
        recording_fetch_enqueued = False

        if status_code == "in_call_recording":
            transitioned_cr = await _on_in_call_recording(
                supabase, recall_bot, update_data, now_iso, bot_id,
            )

        elif status_code == "call_ended":
            update_data["left_at"] = now_iso
            update_data["status"] = "processing"
            if recall_bot.get("error_code") != "not_admitted_alert_sent":
                update_data["error_code"] = "call_ended"
            update_data["error_sub_code"] = sub_code
            utterances.clear_utterances(recall_bot["id"])

        elif status_code == "done":
            utterances.clear_utterances(recall_bot["id"])
            # Idempotency: webhooks are at-least-once, so a replayed `done`
            # would otherwise re-enqueue the recording fetch — which re-runs
            # _decide_feedback_path and re-fires the feedback Lambda (the
            # May-2026 two-trigger race). The first `done` arrives with the
            # bot in `processing` (set by `call_ended`); a replay sees the
            # row already in `done`. Deterministic, multi-worker safe — no
            # in-memory state, no new column.
            if recall_bot.get("status") == "done":
                logger.info(
                    f"Webhook: duplicate done event for bot={bot_id} "
                    f"(already done) — skipping recording fetch re-enqueue"
                )
            else:
                # Lazy import: recording_handler imports from this module too.
                from app.services.recall_webhook import recording_handler
                background_tasks.add_task(
                    recording_handler.fetch_and_store_recording,
                    bot_id,
                    recall_bot["id"],
                    recall_bot.get("candidate_round_id"),
                    recall_bot.get("requisition_id"),
                )
                recording_fetch_enqueued = True

        elif status_code == "fatal":
            utterances.clear_utterances(recall_bot["id"])
            if recall_bot.get("error_code") != "not_admitted_alert_sent":
                update_data["error_code"] = "fatal"
            update_data["error_sub_code"] = sub_code
            transitioned_cr = await _rollback_cr_to_scheduled(
                supabase, recall_bot.get("candidate_round_id")
            )

        await supabase.table("recall_bots")\
            .update(update_data)\
            .eq("id", recall_bot["id"])\
            .execute_async()

        # Not-admitted notifier — only when bot was blocked on entry.
        not_admitted_enqueued = False
        if (
            status_code in ("fatal", "call_ended")
            and is_not_admitted_sub_code(sub_code)
            and recall_bot.get("candidate_round_id")
            and recall_bot.get("error_code") != "not_admitted_alert_sent"
        ):
            from app.services.recall_webhook import notifications
            background_tasks.add_task(
                notifications.notify_bot_not_admitted,
                recall_bot,
            )
            not_admitted_enqueued = True

        return BotStatusOutcome(
            bot_id=bot_id,
            db_status=mapped_status,
            transitioned_cr=transitioned_cr,
            not_admitted_enqueued=not_admitted_enqueued,
            recording_fetch_enqueued=recording_fetch_enqueued,
        )


# ---------------------------------------------------------------------------
# helpers — kept private so the public surface is just `handle_bot_status_change`
# ---------------------------------------------------------------------------


async def _load_bot(supabase, recall_bot_id: str) -> Optional[dict]:
    """Fetch the recall_bots row for a Recall bot UUID. Returns the row
    dict or None when unknown — Recall sometimes sends webhooks for bots
    we've already cancelled and deleted, which is fine to ignore."""
    result = await supabase.table("recall_bots")\
        .select("*")\
        .eq("recall_bot_id", recall_bot_id)\
        .execute_async()
    rows = result.data or []
    return rows[0] if rows else None


async def _on_in_call_recording(
    supabase,
    recall_bot: dict,
    update_data: dict,
    now_iso: str,
    bot_id: str,
) -> bool:
    """Side effects for the `in_call_recording` event:
      - set joined_at on recall_bots
      - flip candidate_rounds.status pending/scheduled → in_progress
      - charge an interview credit (idempotent via CAS on credit_charged)

    Returns True if candidate_rounds.status was transitioned.
    """
    update_data["joined_at"] = now_iso
    update_data["feedback_status"] = "waiting_for_leave"

    cr_id = recall_bot.get("candidate_round_id")
    transitioned = False
    if cr_id:
        cr_update = await supabase.table("candidate_rounds")\
            .update({"status": "in_progress", "started_at": now_iso})\
            .eq("id", cr_id)\
            .execute_async()
        transitioned = bool(cr_update.data)

    # Credit charge — CAS-guarded so a webhook replay doesn't double-charge.
    if not recall_bot.get("credit_charged"):
        cas = await supabase.table("recall_bots")\
            .update({"credit_charged": True})\
            .eq("id", recall_bot["id"])\
            .eq("credit_charged", False)\
            .execute_async()
        if cas.data and cr_id:
            await _charge_interview_credit(supabase, cr_id, bot_id)
        # Reflect the CAS write so the bulk update below doesn't clobber it.
        update_data["credit_charged"] = True

    return transitioned


async def _charge_interview_credit(supabase, cr_id: str, bot_id: str) -> None:
    """Resolve org_id from the candidate_round and decrement an interview
    credit via the shared `use_credit_atomic` Postgres RPC.

    Idempotency: this is gated by a CAS update on `recall_bots.credit_charged`
    (see the caller in `_on_in_call_recording`), so a webhook replay never
    double-charges. If v1's webhook handler also receives the same event,
    the second arrival sees `credit_charged=true` and short-circuits
    before reaching here.

    Failures are logged at WARNING and swallowed — losing a credit charge
    is preferable to blocking the interview lifecycle.
    """
    org_id = await _resolve_org_id(supabase, cr_id)
    if not org_id:
        logger.warning(
            f"Webhook: cannot charge credit — no org_id resolvable for cr={cr_id} bot={bot_id}"
        )
        return

    from app.services.credit_service import use_credit
    try:
        await use_credit(org_id, "interview")
        logger.info(f"Webhook: interview credit charged org={org_id} bot={bot_id}")
    except Exception as e:
        logger.warning(
            f"Webhook: credit charge failed org={org_id} bot={bot_id} err={e} — interview proceeds"
        )


async def _resolve_org_id(supabase, cr_id: str) -> Optional[str]:
    """Walk candidate_rounds → candidates → requisitions.organization_id."""
    row = await supabase.table("candidate_rounds")\
        .select("candidates(requisition_id, requisitions:requisition_id(organization_id))")\
        .eq("id", cr_id)\
        .execute_async()
    if not row.data:
        return None
    cand = row.data[0].get("candidates") or {}
    req = cand.get("requisitions") or {}
    return req.get("organization_id")


async def _rollback_cr_to_scheduled(supabase, cr_id: Optional[str]) -> bool:
    """On `fatal`, roll the candidate_round back to `scheduled` so the
    recruiter can reschedule. Bounded to rows currently in {pending,
    scheduled} — once the call started (in_progress) we don't reverse it.
    """
    if not cr_id:
        return False
    res = await supabase.table("candidate_rounds")\
        .update({"status": "scheduled"})\
        .eq("id", cr_id)\
        .in_("status", ["pending", "scheduled"])\
        .execute_async()
    return bool(res.data)
