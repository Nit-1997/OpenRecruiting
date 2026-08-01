"""
Helpers for deciding whether a transcript captured "enough" interviewer
feedback during the call to skip the post-interview "please add feedback"
email and go straight to the Lambda.

These are pure functions over Recall's transcript shape — no DB, no side
effects. Extracted from v1 (`webhooks/recall.py:148-323`) so the recording
handler stays focused on orchestration.

Why this exists: when the interviewer dictates feedback live (via the
voice agent or the "Scout on" chat trigger), Recall's transcript already
has the content we need. Triggering the Lambda immediately gets the
recruiter their feedback faster.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from app.services.recall_webhook.constants import (
    BOT_SPEAKER_NAMES,
    PARTIAL_MIN_INTERVIEWER_CHARS,
    PARTIAL_MIN_INTERVIEWER_TURNS,
)


# `feedback_transcript` is a plain-text format the voice agent writes to
# `transcripts.feedback_transcript`. Each interviewer line starts with
# "interviewer:". Anything else is candidate or system commentary.
_INTERVIEWER_LINE_RE = re.compile(r"^interviewer\s*:\s*(.+)$", re.IGNORECASE)


def feedback_start_offset_seconds(
    feedback_started_at: str | None,
    joined_at: str | None,
) -> float | None:
    """Seconds between bot join and feedback collection start. Used to
    slice transcript segments down to "the feedback portion" when the
    feedback transcript itself is missing.

    Uses stdlib `datetime.fromisoformat` — v2 doesn't ship dateutil and
    we don't want to add it just for this one parse. Python 3.11+
    fromisoformat handles offset-bearing ISO-8601 the same way dateutil
    does for our inputs (Recall + our own writes).
    """
    if not feedback_started_at or not joined_at:
        return None
    try:
        feedback_dt = datetime.fromisoformat(feedback_started_at.replace("Z", "+00:00"))
        joined_dt = datetime.fromisoformat(joined_at.replace("Z", "+00:00"))
        return (feedback_dt - joined_dt).total_seconds()
    except (TypeError, ValueError):
        return None


def is_meaningful_partial_feedback(
    feedback_transcript: str | None,
    fallback_segments: list[dict] | str | None,
    feedback_start_seconds: float | None,
    candidate_participant_id: int | None = None,
    candidate_names: set[str] | None = None,
) -> tuple[bool, str, int, int]:
    """Decide if the captured feedback meets the minimum bar to trigger
    the Lambda directly.

    Returns `(ready, source, turns, chars)` so callers can log the
    decision lineage.

    Tries the dedicated `feedback_transcript` text first; falls back to
    counting interviewer turns inside Recall segments after the
    feedback-start offset. The thresholds (1 turn, 150 chars) match v1.

    The interviewer is identified by the HOST signal / participant id — a
    host/tenant segment ALWAYS counts, and the candidate is excluded by
    `candidate_participant_id` (preferred) or, when unknown, by name
    (`candidate_names`). This stops a name collision (interviewer shares
    the candidate's name) from zeroing out real interviewer feedback.
    """
    if feedback_transcript and feedback_transcript.strip():
        turns, chars = _interviewer_metrics_from_feedback_transcript(feedback_transcript)
        if turns > 0:
            ready = (
                turns >= PARTIAL_MIN_INTERVIEWER_TURNS
                and chars >= PARTIAL_MIN_INTERVIEWER_CHARS
            )
            return ready, "feedback_transcript", turns, chars
        # Voice agent fired but wrote nothing meaningful → fall through.
        source = "segments_secondary"
    else:
        source = "segments_fallback"

    turns, chars = _interviewer_metrics_from_segments(
        fallback_segments,
        feedback_start_seconds,
        candidate_participant_id,
        candidate_names,
    )
    # BE-A4a: require a REAL feedback_start_offset before the segment path
    # can mark `ready`. Without one, _interviewer_metrics_from_segments
    # falls back to the last-20%-of-segments heuristic, which can mis-fire
    # the Lambda on short interviews (the interviewer simply speaking last
    # is not evidence of dictated feedback). We still surface turns/chars
    # for log lineage, but readiness stays False so the email path runs.
    ready = (
        feedback_start_seconds is not None
        and turns >= PARTIAL_MIN_INTERVIEWER_TURNS
        and chars >= PARTIAL_MIN_INTERVIEWER_CHARS
    )
    return ready, source, turns, chars


# ---------------------------------------------------------------------------
# private helpers
# ---------------------------------------------------------------------------


def _interviewer_metrics_from_feedback_transcript(
    feedback_transcript: str,
) -> tuple[int, int]:
    """Count interviewer-prefixed lines in the voice-agent transcript."""
    turns = 0
    chars = 0
    for raw_line in feedback_transcript.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _INTERVIEWER_LINE_RE.match(line)
        if not match:
            continue
        content = match.group(1).strip()
        if not content:
            continue
        turns += 1
        chars += len(content)
    return turns, chars


def _interviewer_metrics_from_segments(
    segments: list[dict] | str | None,
    feedback_start_seconds: float | None,
    candidate_participant_id: int | None,
    candidate_names: set[str] | None,
) -> tuple[int, int]:
    """Count interviewer segments. An interviewer is anyone who is NOT the
    Scout bot and NOT the candidate. Host/tenant participants are never the
    candidate (fixes the name-collision case)."""
    if isinstance(segments, str):
        try:
            segments = json.loads(segments)
        except Exception:
            return 0, 0
    if not isinstance(segments, list):
        return 0, 0

    if feedback_start_seconds is None:
        total = len(segments)
        if total == 0:
            return 0, 0
        segments = segments[max(0, int(total * 0.8)):]

    names = candidate_names or set()
    turns = 0
    chars = 0
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        speaker = _segment_speaker(segment)
        if not speaker or speaker in BOT_SPEAKER_NAMES:
            continue  # the Scout bot
        if _is_candidate_segment(segment, speaker, candidate_participant_id, names):
            continue  # the candidate
        text = _segment_text(segment, feedback_start_seconds)
        if not text:
            continue
        turns += 1
        chars += len(text)
    return turns, chars


def _is_candidate_segment(
    segment: dict,
    speaker: str,
    candidate_participant_id: int | None,
    candidate_names: set[str],
) -> bool:
    """A host/tenant is never the candidate. Otherwise match by participant
    id when known, else fall back to name."""
    participant = segment.get("participant") or {}
    if participant.get("is_host") or participant.get("is_tenant"):
        return False
    if candidate_participant_id is not None:
        return participant.get("id") == candidate_participant_id
    return speaker in candidate_names


def _segment_speaker(segment: dict) -> str:
    """Speaker name lowercased + stripped, tolerating Recall's two shapes."""
    participant = segment.get("participant") or {}
    speaker = ""
    if isinstance(participant, dict):
        speaker = participant.get("name") or participant.get("display_name") or ""
    if not speaker:
        raw = segment.get("speaker") or segment.get("speaker_name") or ""
        if isinstance(raw, dict):
            speaker = raw.get("name") or raw.get("display_name") or ""
        elif isinstance(raw, str):
            speaker = raw
    return str(speaker).strip().lower()


def _segment_text(segment: dict, feedback_start_seconds: float | None) -> str:
    """Stitch words into text, filtering by the feedback-start offset
    when one is supplied."""
    words = segment.get("words")
    if isinstance(words, list) and words:
        parts: list[str] = []
        for w in words:
            if not isinstance(w, dict):
                continue
            token = (w.get("text") or "").strip()
            if not token:
                continue
            if feedback_start_seconds is not None:
                ts = _relative_word_ts(w)
                if ts is None or ts < feedback_start_seconds:
                    continue
            parts.append(token)
        return " ".join(parts).strip()

    raw_text = segment.get("text")
    if isinstance(raw_text, str):
        if feedback_start_seconds is not None:
            seg_ts = _segment_ts(segment)
            if seg_ts is None or seg_ts < feedback_start_seconds:
                return ""
        return raw_text.strip()

    return ""


def _relative_word_ts(word: dict) -> float | None:
    start = word.get("start_timestamp")
    if isinstance(start, dict):
        rel = start.get("relative")
        return float(rel) if isinstance(rel, (int, float)) else None
    if isinstance(start, (int, float)):
        return float(start)
    return None


def _segment_ts(segment: dict) -> float | None:
    start = segment.get("start_timestamp")
    if isinstance(start, dict):
        rel = start.get("relative")
        return float(rel) if isinstance(rel, (int, float)) else None
    if isinstance(start, (int, float)):
        return float(start)
    alt = segment.get("start")
    if isinstance(alt, (int, float)):
        return float(alt)
    return None
