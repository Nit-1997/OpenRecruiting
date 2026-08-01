"""
Feedback-collection orchestrator — decides HOW to gather interviewer
feedback once the bot is ready to ask.

Three paths in priority order:
  1. Voice agent (VOICE_ENABLED + bot has a voice_session_token):
     activate the Pipecat voice agent, send a chat message announcing it.
  2. Chat command path (reason='chat_command'): the interviewer pinged
     "Scout on" / "yes" — send scorecard questions as chat messages.
  3. Default (e.g. candidate left without a chat ping): prompt the
     interviewer with "Type 'yes' in chat to start collecting feedback."

Ported from `backend/v1/app/api/v1/webhooks/recall.py:1237-1317`.

The `_materialize_missing_detection_round` repair path is calendar-
intelligence-specific and STAYS in v1. v2 callers are guaranteed to have
a candidate_round_id since they came through v2's schedule RPC.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks

from app.config import get_settings
from app.logging_config import get_logger
from app.services.recall_service import get_recall_service
from app.services.supabase import get_supabase_admin_client


logger = get_logger(__name__)


async def trigger_feedback_collection(
    recall_bot: dict,
    recall_bot_id: str,
    reason: str,
    background_tasks: BackgroundTasks,
) -> None:
    """Route to the right feedback-collection path based on bot config
    and the trigger reason.

    `reason` is one of:
      - 'participant_leave' — candidate dropped from the call
      - 'chat_command'      — interviewer typed "Scout on" / "yes"
      - 'retroactive'       — JIT detection completed after the leave
    """
    settings = get_settings()
    candidate_round_id = recall_bot.get("candidate_round_id")

    # Voice path: only when feature flag is on AND we provisioned a token.
    if settings.VOICE_ENABLED and recall_bot.get("voice_session_token"):
        if not candidate_round_id:
            await _fallback_missing_round(recall_bot, recall_bot_id, reason, background_tasks)
            return
        await _activate_voice_agent(recall_bot, recall_bot_id, reason)
        return

    # Chat-command path: interviewer asked for it directly.
    if reason == "chat_command":
        if not candidate_round_id:
            await _fallback_missing_round(recall_bot, recall_bot_id, reason, background_tasks)
            return
        await _start_chat_feedback(recall_bot, recall_bot_id, candidate_round_id, background_tasks)
        return

    # Default: prompt the interviewer with the "type yes" message.
    await _prompt_interviewer(recall_bot, recall_bot_id, reason, background_tasks)


# ---------------------------------------------------------------------------
# private helpers — one path each
# ---------------------------------------------------------------------------


async def _activate_voice_agent(
    recall_bot: dict,
    recall_bot_id: str,
    reason: str,
) -> None:
    logger.info(
        f"feedback: activating voice agent bot={recall_bot['id']} reason={reason}"
    )
    await _update_bot(recall_bot["id"], {
        "feedback_status": "voice_active",
        "voice_session_status": "activating",
        "feedback_started_at": datetime.now(timezone.utc).isoformat(),
    })
    recall_service = get_recall_service()
    try:
        await recall_service.send_chat_message(
            recall_bot_id,
            "OpenRecruiting will now collect your interview feedback. "
            "Please stay on the call for a moment.",
        )
    except Exception as e:
        logger.warning(f"feedback: voice activation chat failed bot={recall_bot['id']}: {e}")
    finally:
        await recall_service.close()


async def _start_chat_feedback(
    recall_bot: dict,
    recall_bot_id: str,
    candidate_round_id: str,
    background_tasks: BackgroundTasks,
) -> None:
    logger.info(
        f"feedback: starting chat collection bot={recall_bot['id']} cr={candidate_round_id}"
    )
    await _update_bot(recall_bot["id"], {
        "feedback_status": "collecting",
        "feedback_started_at": datetime.now(timezone.utc).isoformat(),
    })
    # Lazy import to break the chat_handler → feedback_collection → chat_handler cycle.
    from app.services.recall_webhook import chat_handler
    background_tasks.add_task(
        chat_handler.send_scorecard_questions,
        recall_bot_id,
        candidate_round_id,
    )


async def _prompt_interviewer(
    recall_bot: dict,
    recall_bot_id: str,
    reason: str,
    background_tasks: BackgroundTasks,
) -> None:
    logger.info(
        f"feedback: prompting interviewer bot={recall_bot['id']} reason={reason}"
    )
    update_payload: dict = {"feedback_status": "waiting_for_yes"}
    # Start the feedback clock on participant-leave so the partial-feedback
    # decision in the recording handler has a valid offset.
    if reason == "participant_leave" and not recall_bot.get("feedback_started_at"):
        update_payload["feedback_started_at"] = datetime.now(timezone.utc).isoformat()
    await _update_bot(recall_bot["id"], update_payload)
    from app.services.recall_webhook import chat_handler
    background_tasks.add_task(chat_handler.send_feedback_prompt, recall_bot_id)


async def _fallback_missing_round(
    recall_bot: dict,
    recall_bot_id: str,
    reason: str,
    background_tasks: BackgroundTasks,
) -> None:
    """No candidate_round_id available — flag the bot and still prompt.
    v2-scheduled bots should never hit this; logging at WARNING so it
    stands out if it does."""
    logger.warning(
        f"feedback: trigger fallback missing candidate_round_id "
        f"bot={recall_bot.get('id')} recall_bot_id={recall_bot_id} reason={reason}"
    )
    await _update_bot(recall_bot["id"], {
        "feedback_status": "waiting_for_yes",
        "voice_session_status": "dormant",
        "error_code": "missing_candidate_round",
    })
    from app.services.recall_webhook import chat_handler
    background_tasks.add_task(chat_handler.send_feedback_prompt, recall_bot_id)


# ---------------------------------------------------------------------------
# shared utilities — kept here (not in a "utils" file) because they're
# only used inside this module
# ---------------------------------------------------------------------------


async def _update_bot(db_id: str, update_data: dict) -> None:
    supabase = get_supabase_admin_client()
    await supabase.table("recall_bots")\
        .update(update_data)\
        .eq("id", db_id)\
        .execute_async()


async def get_recall_bot_by_recall_id(recall_bot_id: str) -> Optional[dict]:
    """Lookup helper shared by participant + chat + transcript handlers.
    Returns the row dict or None when the bot isn't in our DB (could be
    a webhook for a bot we just cancelled — fine to drop)."""
    supabase = get_supabase_admin_client()
    result = await supabase.table("recall_bots")\
        .select("*")\
        .eq("recall_bot_id", recall_bot_id)\
        .execute_async()
    rows = result.data or []
    return rows[0] if rows else None
