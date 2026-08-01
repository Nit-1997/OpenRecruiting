"""
`transcript.data` event handler — accumulates utterances and triggers
candidate detection once enough participants have spoken.

Two responsibilities (still SRP because both are tightly coupled to the
utterance buffer):
  1. Append the new transcript words to the per-bot per-participant
     buffer in `app.services.recall_webhook.utterances`.
  2. When the buffer crosses the configured thresholds (N participants,
     K chars each), enqueue a background detection run.

The detection run itself lives in `_run_detection_and_handle` here
(rather than inside detection_service) because it has webhook-flow
side effects: it fetches a fresh recall_bot row, may stash a
retroactive-trigger flag, and prompts the interviewer if the candidate
already left.

Ported from `backend/v1/app/api/v1/webhooks/recall.py:1500-1587`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import BackgroundTasks

from app.config import get_settings
from app.logging_config import get_logger
from app.services.candidate_detection_service import (
    append_utterance,
    check_retroactive_trigger,
    get_utterances,
    run_detection,
    store_detection_result,
)
from app.services.recall_webhook import participant_handler
from app.services.recall_webhook.feedback_collection import (
    get_recall_bot_by_recall_id,
)
from app.services.supabase import get_supabase_admin_client


logger = get_logger(__name__)


# Map recall_bot_id → bot_db_id, so we don't query DB on every word event.
# Cleared via constants on bot status terminal events.
_bot_id_map: dict[str, str] = {}


async def handle_transcript_data(
    recall_bot_id: str,
    payload_data: dict,
    background_tasks: BackgroundTasks,
) -> None:
    """Buffer this transcript event and maybe schedule a detection run.

    Returns silently when:
      - detection is disabled
      - the payload has no usable text
      - the bot isn't in our DB or detection already completed
      - thresholds for triggering detection aren't met yet
      - a detection run is already in flight for this bot
    """
    settings = get_settings()
    if not settings.CANDIDATE_DETECT_ENABLED:
        return

    transcript = payload_data.get("data") or {}
    participant = transcript.get("participant") or {}
    participant_id = participant.get("id")
    words = transcript.get("words") or []

    if not participant_id or not words:
        return

    text = " ".join((w.get("text") or "") for w in words if isinstance(w, dict))
    text = text.strip()
    if not text:
        return

    bot_db_id = await _resolve_bot_db_id(recall_bot_id)
    if not bot_db_id:
        return

    max_chars = settings.CANDIDATE_DETECT_CHAR_THRESHOLD * 2
    append_utterance(bot_db_id, str(participant_id), text, max_chars)

    # Don't pile up detections — one in-flight at a time.
    if bot_db_id in participant_handler._detection_in_flight:
        return

    utterances = get_utterances(bot_db_id)
    qualifying = sum(
        1 for v in utterances.values()
        if len(v) >= settings.CANDIDATE_DETECT_CHAR_THRESHOLD
    )
    if qualifying < settings.CANDIDATE_DETECT_MIN_PARTICIPANTS:
        return

    participant_handler._detection_in_flight.add(bot_db_id)
    snapshot = dict(utterances)  # detach from the live buffer
    background_tasks.add_task(
        _run_detection_and_handle, recall_bot_id, bot_db_id, snapshot,
    )


# ---------------------------------------------------------------------------
# private helpers
# ---------------------------------------------------------------------------


async def _resolve_bot_db_id(recall_bot_id: str) -> str | None:
    """Resolve and cache the bot's DB id. Skips when detection is already
    complete (no point buffering more utterances)."""
    bot_db_id = _bot_id_map.get(recall_bot_id)
    if bot_db_id:
        return bot_db_id
    recall_bot = await get_recall_bot_by_recall_id(recall_bot_id)
    if not recall_bot:
        return None
    if recall_bot.get("detection_completed"):
        return None
    bot_db_id = recall_bot["id"]
    _bot_id_map[recall_bot_id] = bot_db_id
    return bot_db_id


async def _run_detection_and_handle(
    recall_bot_id: str,
    bot_db_id: str,
    utterances_snapshot: dict[str, str],
) -> None:
    """Background task: run detection, persist result, fire retroactive
    feedback trigger if the candidate already left."""
    try:
        supabase = get_supabase_admin_client()
        fresh = await supabase.table("recall_bots")\
            .select("*")\
            .eq("id", bot_db_id)\
            .single()\
            .execute_async()
        if not fresh.data:
            return
        recall_bot = fresh.data

        if recall_bot.get("detection_completed"):
            _bot_id_map.pop(recall_bot_id, None)
            return

        result = await run_detection(recall_bot, utterances_snapshot)
        if not result:
            return

        await store_detection_result(bot_db_id, result, utterances_snapshot)
        _bot_id_map.pop(recall_bot_id, None)
        logger.info(
            f"transcript: detection stored bot={bot_db_id} "
            f"pid={result['candidate_participant_id']} confidence={result['confidence']}"
        )

        # Retroactive feedback trigger: detection completed AFTER candidate
        # left. Prompt the interviewer now.
        should_trigger = await check_retroactive_trigger(recall_bot, result)
        if should_trigger and recall_bot.get("feedback_status") == "waiting_for_leave":
            from app.services.recall_webhook import chat_handler
            logger.info(
                f"transcript: retroactive feedback trigger "
                f"cr={recall_bot.get('candidate_round_id')}"
            )
            update_payload: dict = {"feedback_status": "waiting_for_yes"}
            if not recall_bot.get("feedback_started_at"):
                update_payload["feedback_started_at"] = datetime.now(timezone.utc).isoformat()
            await supabase.table("recall_bots")\
                .update(update_payload)\
                .eq("id", bot_db_id)\
                .execute_async()
            await chat_handler.send_feedback_prompt(recall_bot_id)

    finally:
        participant_handler._detection_in_flight.discard(bot_db_id)
