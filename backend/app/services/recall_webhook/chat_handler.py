"""
`participant_events.chat_message` handler + scorecard / prompt senders.

Handles the in-meeting chat triggers:
  - "Scout on" (and common typo variants) — start feedback collection
  - "yes" / "y" (only when feedback_status == 'waiting_for_yes') — same

Also exposes the message senders used by feedback_collection and the
retroactive trigger path:
  - `send_feedback_prompt`     — "Type 'yes' to start collecting feedback"
  - `send_scorecard_questions` — walks the round's feedback_questions

Ported from `backend/v1/app/api/v1/webhooks/recall.py:1454-1681`.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

from fastapi import BackgroundTasks

from app.logging_config import get_logger
from app.services.recall_service import get_recall_service
from app.services.recall_webhook.feedback_collection import (
    get_recall_bot_by_recall_id,
    trigger_feedback_collection,
)
from app.services.supabase import get_supabase_admin_client


logger = get_logger(__name__)


# "Scout on" command with typo tolerance. The interviewer types this in the
# meeting chat to start feedback collection, so it has to survive being typed
# quickly on a phone: the explicit set covers the common shapes and the fuzzy
# pattern catches doubled letters and a missing/extra separator.
_ASSISTANT_ON_VARIANTS = frozenset({
    "scout on", "scouton", "scout-on",
    "scot on", "scoton", "scot-on",
    "scuot on", "scuoton",
})
_ASSISTANT_ON_FUZZY = re.compile(r"^sc[ou]+t+\s*[-]?\s*on$")


def is_assistant_on_command(message: str) -> bool:
    """True if `message` looks like a "Scout on" command (case- and
    spacing-insensitive, tolerates common typos)."""
    if not message:
        return False
    normalised = re.sub(r"\s+", " ", message.lower().strip())
    if normalised in _ASSISTANT_ON_VARIANTS:
        return True
    return bool(_ASSISTANT_ON_FUZZY.match(normalised))


async def handle_chat_message(
    recall_bot_id: str,
    payload_data: dict,
    background_tasks: BackgroundTasks,
) -> None:
    """Detect "Scout on" / "yes" triggers and start feedback collection.

    Silently ignores messages when:
      - bot is unknown
      - voice agent is already active (no chat-driven path)
      - feedback_status isn't a waiting state
      - the message text doesn't match a trigger
    """
    recall_bot = await get_recall_bot_by_recall_id(recall_bot_id)
    if not recall_bot:
        logger.warning(f"chat: bot not found recall_bot_id={recall_bot_id}")
        return

    feedback_status = recall_bot.get("feedback_status")
    if feedback_status == "voice_active":
        logger.debug("chat: voice session active — ignoring message")
        return
    if feedback_status not in ("waiting_for_leave", "waiting_for_yes"):
        logger.debug(f"chat: not awaiting trigger status={feedback_status}")
        return

    chat = payload_data.get("data") or {}
    inner = chat.get("data") or {}
    message = (inner.get("text") or "").strip()
    logger.debug(f"chat: message='{message}' status={feedback_status}")

    should_trigger = False
    if is_assistant_on_command(message):
        logger.info(f"chat: 'Scout on' command detected: '{message}'")
        should_trigger = True
    elif feedback_status == "waiting_for_yes" and message.lower() in ("yes", "y"):
        logger.info("chat: 'yes' response detected")
        should_trigger = True

    if should_trigger:
        await trigger_feedback_collection(
            recall_bot, recall_bot_id, "chat_command", background_tasks,
        )


# ---------------------------------------------------------------------------
# senders — used by feedback_collection + retroactive trigger
# ---------------------------------------------------------------------------


async def send_feedback_prompt(recall_bot_id: str) -> None:
    """Send the "Type 'yes' in chat to start collecting your feedback"
    nudge to the meeting."""
    recall_service = get_recall_service()
    try:
        await recall_service.send_chat_message(
            recall_bot_id,
            "Type 'yes' in chat to start collecting your feedback.",
        )
    except Exception as e:
        logger.error(f"chat: send feedback prompt failed bot={recall_bot_id}: {e}")
    finally:
        await recall_service.close()


async def send_scorecard_questions(recall_bot_id: str, candidate_round_id: str) -> None:
    """Walk the round's feedback_questions and post each as a chat message,
    followed by a verdict prompt and a polite sign-off. Marks the bot's
    feedback_status='completed' when done so the recording handler later
    routes through the Lambda branch."""
    if not candidate_round_id:
        logger.warning("chat: send_scorecard_questions called without candidate_round_id")
        return

    logger.info(f"chat: send_scorecard bot={recall_bot_id} cr={candidate_round_id}")

    recall_service = get_recall_service()
    supabase = get_supabase_admin_client()

    try:
        cr_result = await supabase.table("candidate_rounds")\
            .select("round_id")\
            .eq("id", candidate_round_id)\
            .execute_async()
        if not cr_result.data:
            logger.warning(f"chat: no candidate_round for cr={candidate_round_id}")
            return

        round_id = cr_result.data[0]["round_id"]
        questions_result = await supabase.table("feedback_questions")\
            .select("question_number, heading, description")\
            .eq("round_id", round_id)\
            .is_null("deleted_at")\
            .order("question_number")\
            .execute_async()
        questions = questions_result.data or []
        logger.info(f"chat: {len(questions)} scorecard questions for round={round_id}")

        await recall_service.send_chat_message(
            recall_bot_id,
            "Let's gather some feedback! Feel free to answer each question out loud.",
        )
        await asyncio.sleep(1)

        for q in questions:
            await recall_service.send_chat_message(
                recall_bot_id,
                _format_question_for_chat(q),
            )
            await asyncio.sleep(0.5)

        await asyncio.sleep(1)
        await recall_service.send_chat_message(
            recall_bot_id,
            "Finally: What's your verdict? (strong_no / no / maybe / yes / strong_yes)",
        )
        await asyncio.sleep(1)
        await recall_service.send_chat_message(
            recall_bot_id,
            "Feel free to leave once you've finished. Have a good day!",
        )

        await supabase.table("recall_bots")\
            .update({
                "feedback_status": "completed",
                "feedback_completed_at": datetime.now(timezone.utc).isoformat(),
            })\
            .eq("recall_bot_id", recall_bot_id)\
            .execute_async()

    except Exception as e:
        logger.error(
            f"chat: send_scorecard_questions failed cr={candidate_round_id}: {e}",
            exc_info=True,
        )
    finally:
        await recall_service.close()


# ---------------------------------------------------------------------------
# private helpers
# ---------------------------------------------------------------------------


# Recall's chat message field is capped at 500 chars; we truncate descriptions
# to fit. Number + heading take a few chars; reserve the rest for description.
_CHAT_MAX_CHARS = 500


def _format_question_for_chat(q: dict) -> str:
    """Format `{question_number}. {heading}: <description>` with safe
    truncation."""
    base = f"{q.get('question_number')}. {q.get('heading')}:"
    desc = q.get("description")
    if not desc:
        return base[:_CHAT_MAX_CHARS]

    # 490 leaves a tiny safety margin before the hard cap; matches v1.
    remaining = 490 - len(base)
    if remaining <= 10:
        return base[:_CHAT_MAX_CHARS]
    if len(desc) > remaining:
        desc = desc[: remaining - 3] + "..."
    return f"{base}\n{desc}"[:_CHAT_MAX_CHARS]
