"""
In-memory utterance buffer used by realtime transcript detection.

Lives at module scope because the realtime webhook is fire-and-forget —
Recall pushes one event per spoken word/segment and we accumulate them
until detection has enough to run. The buffer is keyed by
`recall_bot.id` (the DB UUID) so multiple concurrent interviews don't
mix utterances.

Trade-off accepted: process-local state. If we scale to multi-worker
uvicorn, each worker sees only the utterances it received — detection
may miss some. Acceptable because realtime detection is a best-effort
nice-to-have on top of the post-call detection in the recording handler.

v1 ships an identical implementation in
`backend/v1/app/services/candidate_detection_service.py:16-29`.
We re-implement here (not import) to keep v2 self-contained per the
intentional v1/v2 split.
"""

from __future__ import annotations

import threading


# bot_db_id (UUID string) → { participant_id → utterance_text }
_UTTERANCES: dict[str, dict[str, str]] = {}
_LOCK = threading.Lock()


def get_utterances(bot_db_id: str) -> dict[str, str]:
    """Snapshot the utterances for a bot. Returns a copy so callers can't
    mutate the live buffer through the reference."""
    with _LOCK:
        return dict(_UTTERANCES.get(bot_db_id, {}))


def append_utterance(
    bot_db_id: str,
    participant_id: str,
    text: str,
    max_chars: int,
) -> None:
    """Append `text` to the running transcript for one participant.

    The per-participant buffer is capped at `max_chars`. When exceeded,
    we truncate from the left — keeping the most recent context, which
    is what the detection LLM cares about for "who is talking like a
    candidate right now."
    """
    if not bot_db_id or not participant_id or not text:
        return
    with _LOCK:
        bot_buf = _UTTERANCES.setdefault(bot_db_id, {})
        existing = bot_buf.get(participant_id, "")
        merged = f"{existing} {text}".strip() if existing else text
        if len(merged) > max_chars:
            merged = merged[-max_chars:]
        bot_buf[participant_id] = merged


def clear_utterances(bot_db_id: str) -> None:
    """Drop the buffer for a bot. Called on `call_ended` / `done` /
    `fatal` so we don't leak memory across rounds."""
    with _LOCK:
        _UTTERANCES.pop(bot_db_id, None)


def total_chars(bot_db_id: str) -> int:
    """Sum of buffered chars across all participants for a bot. Used by
    the transcript handler to decide when to trigger detection."""
    with _LOCK:
        bot_buf = _UTTERANCES.get(bot_db_id, {})
        return sum(len(v) for v in bot_buf.values())
