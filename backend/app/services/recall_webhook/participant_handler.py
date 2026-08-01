"""
Participant join + leave handlers — track participants on recall_bots
and drive candidate-drop detection.

Drop heuristic (in priority order, ported from v1):
  1. **Detection-completed path** (preferred): if we've already run the
     LLM detection and we know which participant_id is the candidate,
     trigger feedback collection only when THAT participant leaves and
     confidence ≥ threshold.
  2. **JIT detection**: if leave fires before detection finished AND
     CANDIDATE_DETECT_ENABLED is on, run detection synchronously on the
     current utterance buffer. If it matches the leaving participant with
     high confidence, treat them as the candidate.
  3. **Pure heuristic**: if neither of the above matches, fall back to
     "non-interviewer (not host, not tenant) leaves while an interviewer
     remains in the call" — the leaver is presumed candidate.

When the leaver is an interviewer (is_host or is_tenant), we never
trigger; that's a panellist hopping off.

Single responsibility per function: tracking on join, drop-detection on
leave. The actual feedback trigger logic lives in
`feedback_collection.trigger_feedback_collection`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks

from app.config import get_settings
from app.logging_config import get_logger
from app.services.candidate_detection_service import (
    get_utterances,
    run_detection,
    store_detection_result,
)
from app.services.recall_webhook import end_state
from app.services.recall_webhook.feedback_collection import (
    get_recall_bot_by_recall_id,
    trigger_feedback_collection,
)
from app.services.recall_webhook.interviewer_detection import is_interviewer
from app.services.supabase import get_supabase_admin_client


logger = get_logger(__name__)


# Set of bot DB ids currently running JIT detection. Prevents two
# concurrent participant-leave events from both kicking detection.
_detection_in_flight: set[str] = set()


# ---------------------------------------------------------------------------
# participant_events.join
# ---------------------------------------------------------------------------


async def handle_participant_join(recall_bot_id: str, payload_data: dict) -> None:
    """Add the joining participant to `recall_bots.tracked_participants`."""
    participant = (payload_data.get("data") or {}).get("participant") or {}
    participant_id = participant.get("id")
    participant_name = (participant.get("name") or "").strip()
    is_host = bool(participant.get("is_host"))
    platform = participant.get("platform")
    extra_data = participant.get("extra_data") or {}
    email = participant.get("email")

    recall_bot = await get_recall_bot_by_recall_id(recall_bot_id)
    if not recall_bot:
        return

    tracked = list(recall_bot.get("tracked_participants") or [])

    entry: dict = {
        "id": participant_id,
        "name": participant_name,
        "is_host": is_host,
        "platform": platform,
        "extra_data": extra_data,
        "email": email,
        "joined_at": datetime.now(timezone.utc).isoformat(),
        "left_at": None,
    }
    # Teams enrichment — is_tenant flag tells us the participant belongs
    # to the inviting org (i.e. interviewer, not external candidate).
    teams = extra_data.get("microsoft_teams") if isinstance(extra_data, dict) else None
    if isinstance(teams, dict):
        participant_type = teams.get("participant_type")
        entry["is_tenant"] = participant_type == "inTenant"
        entry["meeting_role"] = teams.get("meeting_role")

    tracked.append(entry)

    update_data: dict = {"tracked_participants": tracked}
    # Fallback: if bot.status_change → in_call_recording was dropped
    # (Recall webhook loss), the first participant join is our latest
    # chance to set feedback_status. Without this, the leave path skips.
    if recall_bot.get("feedback_status") == "none":
        update_data["feedback_status"] = "waiting_for_leave"
        logger.info(
            f"participant: set feedback_status=waiting_for_leave on first join "
            f"bot={recall_bot['id']} (status_change webhook may have been lost)"
        )

    await _update_bot(recall_bot["id"], update_data)
    logger.info(
        f"participant: joined name={participant_name} is_host={is_host} "
        f"platform={platform} is_tenant={entry.get('is_tenant')}"
    )


# ---------------------------------------------------------------------------
# participant_events.leave
# ---------------------------------------------------------------------------


async def handle_participant_leave(
    recall_bot_id: str,
    payload_data: dict,
    background_tasks: BackgroundTasks,
) -> None:
    """Mark the leaver's `left_at` and decide whether this was the
    candidate dropping (→ trigger feedback collection)."""
    participant = (payload_data.get("data") or {}).get("participant") or {}
    participant_id = participant.get("id")
    participant_name = (participant.get("name") or "").strip()

    recall_bot = await get_recall_bot_by_recall_id(recall_bot_id)
    if not recall_bot:
        return

    tracked = list(recall_bot.get("tracked_participants") or [])
    leaving_entry = _mark_left(tracked, participant_id)
    await _update_bot(recall_bot["id"], {"tracked_participants": tracked})

    # Only care about drops while the bot is actively waiting for one.
    if recall_bot.get("feedback_status") != "waiting_for_leave":
        return

    candidate_left = await _is_candidate_drop(
        recall_bot, tracked, leaving_entry or participant,
        participant_id, participant_name,
    )
    if not candidate_left:
        return

    settings = get_settings()
    if not settings.END_STATE_DETECT_ENABLED:
        # Feature off → preserve legacy behaviour (immediate trigger).
        await trigger_feedback_collection(
            recall_bot, recall_bot_id, "participant_leave", background_tasks,
        )
        return

    background_tasks.add_task(
        _confirm_end_and_trigger,
        recall_bot_id,
        recall_bot["id"],
        participant_id,
        settings.END_STATE_GRACE_SECONDS,
        background_tasks,
    )


# ---------------------------------------------------------------------------
# drop-detection — broken into 3 strategies (priority order)
# ---------------------------------------------------------------------------


async def _is_candidate_drop(
    recall_bot: dict,
    tracked: list[dict],
    leaving_participant: dict,
    participant_id,
    participant_name: str,
) -> bool:
    settings = get_settings()

    # Strategy 1 — detection already completed
    if recall_bot.get("detection_completed") and recall_bot.get("detected_candidate_participant_id") is not None:
        decision = _drop_from_completed_detection(
            recall_bot, leaving_participant, participant_id, participant_name, settings,
        )
        if decision is not None:
            return decision
        # decision == None means "low confidence, fall through to heuristic"

    # Strategy 2 — JIT detection
    if not recall_bot.get("detection_completed") and settings.CANDIDATE_DETECT_ENABLED:
        if recall_bot["id"] not in _detection_in_flight:
            _detection_in_flight.add(recall_bot["id"])
            try:
                jit_match = await _drop_from_jit_detection(
                    recall_bot, tracked, leaving_participant,
                    participant_id, participant_name, settings,
                )
                if jit_match:
                    return True
            except Exception as e:
                logger.error(f"participant: JIT detection failed: {e}")
            finally:
                _detection_in_flight.discard(recall_bot["id"])
        else:
            logger.info("participant: JIT detection already in flight — falling to heuristic")

    # Strategy 3 — heuristic
    return _drop_from_heuristic(tracked, leaving_participant, participant_name)


def _drop_from_completed_detection(
    recall_bot: dict,
    leaving_p: dict,
    participant_id,
    participant_name: str,
    settings,
) -> Optional[bool]:
    """Returns True/False if completed detection decides, or None when we
    should fall through to JIT/heuristic."""
    detected_pid = recall_bot["detected_candidate_participant_id"]
    confidence = recall_bot.get("detection_confidence") or 0

    if participant_id != detected_pid:
        logger.info(
            f"participant: non-candidate left name={participant_name} "
            f"(detected_pid={detected_pid}) — ignoring"
        )
        return False

    if confidence < settings.CANDIDATE_DETECT_CONFIDENCE_THRESHOLD:
        logger.info(
            f"participant: low confidence ({confidence}) — falling to heuristic"
        )
        return None

    if is_interviewer(leaving_p):
        logger.info(
            f"participant: detected candidate is is_host/is_tenant — "
            f"detection wrong, falling to heuristic name={participant_name}"
        )
        return None

    logger.info(
        f"participant: detected candidate left name={participant_name} "
        f"confidence={confidence}"
    )
    return True


async def _drop_from_jit_detection(
    recall_bot: dict,
    tracked: list[dict],
    leaving_p: dict,
    participant_id,
    participant_name: str,
    settings,
) -> bool:
    """Run detection synchronously and decide based on its result."""
    # Use the freshest tracked list (the one with left_at just stamped on
    # the leaver) so detection considers leaving as a signal.
    recall_bot_with_leaver = {**recall_bot, "tracked_participants": tracked}
    utterances = get_utterances(recall_bot["id"])
    result = await run_detection(recall_bot_with_leaver, utterances)
    if not result:
        return False

    await store_detection_result(recall_bot["id"], result, dict(utterances))

    if participant_id != result["candidate_participant_id"]:
        return False
    if result["confidence"] < settings.CANDIDATE_DETECT_CONFIDENCE_THRESHOLD:
        return False
    if is_interviewer(leaving_p):
        logger.info(
            f"participant: JIT-detected candidate is interviewer — ignoring "
            f"name={participant_name}"
        )
        return False

    logger.info(
        f"participant: JIT detection matched leaver name={participant_name} "
        f"confidence={result['confidence']}"
    )
    return True


def _drop_from_heuristic(
    tracked: list[dict],
    leaving_p: dict,
    participant_name: str,
) -> bool:
    """Last-resort heuristic: a non-interviewer leaving while an
    interviewer remains is presumed to be the candidate dropping."""
    if is_interviewer(leaving_p):
        logger.info(f"participant: interviewer left — not triggering name={participant_name}")
        return False

    interviewer_remaining = any(
        is_interviewer(p) and p.get("left_at") is None
        for p in tracked
    )
    if not interviewer_remaining:
        logger.info("participant: no interviewer remaining — not triggering (heuristic)")
        return False

    logger.info(
        f"participant: non-interviewer left, interviewer present — "
        f"triggering (heuristic) name={participant_name}"
    )
    return True


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _mark_left(tracked: list[dict], participant_id) -> Optional[dict]:
    """Stamp left_at on the matching entry, return it (or None if not found)."""
    for p in tracked:
        if p.get("id") == participant_id:
            p["left_at"] = datetime.now(timezone.utc).isoformat()
            return p
    return None


async def _update_bot(db_id: str, update_data: dict) -> None:
    supabase = get_supabase_admin_client()
    await supabase.table("recall_bots")\
        .update(update_data)\
        .eq("id", db_id)\
        .execute_async()


# ---------------------------------------------------------------------------
# grace-delayed end-state confirmation
# ---------------------------------------------------------------------------


async def _confirm_end_and_trigger(
    recall_bot_id: str,
    db_id: str,
    dropped_participant_id,
    grace_seconds: int,
    background_tasks: BackgroundTasks,
) -> None:
    """After a grace window, re-evaluate whether the interview actually
    ended. Rejoin during grace → no trigger. Only a wrapping_up/ended
    verdict (≥ threshold) starts feedback collection."""
    if grace_seconds:
        await asyncio.sleep(grace_seconds)

    recall_bot = await get_recall_bot_by_recall_id(recall_bot_id)
    if not recall_bot or recall_bot.get("feedback_status") != "waiting_for_leave":
        return  # already handled / not waiting any more

    settings = get_settings()
    tracked = recall_bot.get("tracked_participants") or []
    transcript_text = end_state.transcript_from_utterances(tracked, get_utterances(db_id))

    verdict = await end_state.evaluate_end_state(
        recall_bot,
        tracked,
        transcript_text,
        trigger="candidate_drop",
        dropped_participant_id=dropped_participant_id,
    )
    if verdict.phase in ("wrapping_up", "ended") and verdict.confidence >= settings.END_STATE_CONFIDENCE_THRESHOLD:
        logger.info(
            f"participant: end-state confirmed ({verdict.phase} {verdict.confidence}) — triggering "
            f"bot={db_id} reason={verdict.source}"
        )
        await trigger_feedback_collection(
            recall_bot, recall_bot_id, "participant_leave", background_tasks,
        )
    else:
        logger.info(
            f"participant: transient drop, not triggering "
            f"phase={verdict.phase} conf={verdict.confidence} bot={db_id}"
        )
