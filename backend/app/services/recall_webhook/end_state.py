"""
Interview end-state detection.

Answers ONE question — "what phase is this interview in?" — and nothing
else (no DB writes, no feedback-collection knowledge). Callers act on the
verdict.

The fuzzy judgment (is a mid-interview silence the end, or a transient
drop?) is done by Claude Sonnet over full context; code enforces only the
unambiguous facts:
  * a candidate who dropped but is present again  -> phase=mid  (cancel)
  * trigger == call_ended                         -> phase=ended (forced)

LLM call mirrors candidate_detection_service Tier 3 (one-shot httpx to the
Anthropic Messages API; ANTHROPIC_API_KEY auth; JSON-only response).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Literal, Optional

import httpx

from app.config import get_settings
from app.logging_config import get_logger
from app.utils import parse_json_response


logger = get_logger(__name__)


Phase = Literal["early", "mid", "wrapping_up", "ended"]
Trigger = Literal["candidate_drop", "call_ended"]


@dataclass(frozen=True)
class EndStateVerdict:
    phase: Phase
    confidence: float
    is_no_show: bool
    reasoning: str
    source: str  # "llm" | "guardrail:call_ended" | "guardrail:rejoin" | "llm_failed"


async def evaluate_end_state(
    recall_bot: dict,
    tracked_participants: list[dict],
    transcript_text: str,
    trigger: Trigger,
    dropped_participant_id: Optional[int] = None,
) -> EndStateVerdict:
    """Judge the interview phase. See module docstring for the contract."""
    # Guardrail 1: the participant who dropped is present again -> not the end.
    if dropped_participant_id is not None:
        entry = next(
            (p for p in tracked_participants if p.get("id") == dropped_participant_id),
            None,
        )
        if entry is not None and entry.get("left_at") is None:
            logger.info(
                f"end-state: dropped participant {dropped_participant_id} rejoined — phase=mid"
            )
            return EndStateVerdict("mid", 1.0, False, "dropped participant rejoined", "guardrail:rejoin")

    raw = await _llm_judge(_build_prompt(recall_bot, tracked_participants, transcript_text, trigger), get_settings())

    if raw is None:
        # Fail safe. Drop -> don't trigger (mid). call_ended -> still ended,
        # infer no-show from the participant list.
        is_no_show = _infer_no_show(tracked_participants)
        phase: Phase = "ended" if trigger == "call_ended" else "mid"
        return EndStateVerdict(phase, 0.0, is_no_show, "llm unavailable — safe default", "llm_failed")

    verdict = EndStateVerdict(
        phase=_coerce_phase(raw.get("phase")),
        confidence=_coerce_confidence(raw.get("confidence")),
        is_no_show=bool(raw.get("is_no_show", False)),
        reasoning=str(raw.get("reasoning", "")),
        source="llm",
    )

    # Guardrail 2: the call is definitively over.
    if trigger == "call_ended":
        return replace(verdict, phase="ended", source="guardrail:call_ended")
    return verdict


# ---------------------------------------------------------------------------
# transcript formatters (callers pick the one matching their data source)
# ---------------------------------------------------------------------------


def transcript_from_segments(segments: Optional[list[dict]]) -> str:
    """Speaker-attributed transcript from stored Recall segments (chronological)."""
    if not isinstance(segments, list):
        return ""
    lines: list[str] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        participant = seg.get("participant") or {}
        name = (participant.get("name") or "speaker").strip()
        is_host = bool(participant.get("is_host") or participant.get("is_tenant"))
        words = seg.get("words")
        if isinstance(words, list) and words:
            text = " ".join((w.get("text") or "").strip() for w in words if isinstance(w, dict)).strip()
        else:
            text = (seg.get("text") or "").strip() if isinstance(seg.get("text"), str) else ""
        if text:
            lines.append(f"{name} (host={is_host}): {text}")
    return "\n".join(lines)


def transcript_from_utterances(tracked_participants: list[dict], utterances: dict) -> str:
    """Speaker-attributed transcript from the in-memory utterance buffer
    ({participant_id: text}). Used at the drop event, before the stored
    transcript exists."""
    by_id = {str(p.get("id")): p for p in tracked_participants}
    lines: list[str] = []
    for pid, text in (utterances or {}).items():
        if not text:
            continue
        p = by_id.get(str(pid), {})
        name = (p.get("name") or "speaker").strip()
        is_host = bool(p.get("is_host") or p.get("is_tenant"))
        lines.append(f"{name} (host={is_host}): {text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# private
# ---------------------------------------------------------------------------


def _infer_no_show(tracked_participants: list[dict]) -> bool:
    """No-show = no non-host/non-tenant participant ever joined."""
    for p in tracked_participants or []:
        if not (p.get("is_host") or p.get("is_tenant")):
            return False
    return True


_VALID_PHASES = ("early", "mid", "wrapping_up", "ended")


def _coerce_phase(value) -> Phase:
    return value if value in _VALID_PHASES else "mid"


def _coerce_confidence(value) -> float:
    """The LLM may return a non-numeric confidence ("high") or one out of range.
    Coerce defensively so a bad value can never raise past evaluate_end_state's
    failsafe (which would fail the webhook instead of yielding a safe verdict)."""
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, c))


def _elapsed_minutes(recall_bot: dict) -> Optional[int]:
    joined = recall_bot.get("joined_at")
    if not joined:
        return None
    try:
        joined_dt = datetime.fromisoformat(str(joined).replace("Z", "+00:00"))
        return int((datetime.now(timezone.utc) - joined_dt).total_seconds() // 60)
    except (TypeError, ValueError):
        return None


def _build_prompt(
    recall_bot: dict,
    tracked_participants: list[dict],
    transcript_text: str,
    trigger: Trigger,
) -> str:
    timeline = []
    for p in tracked_participants or []:
        timeline.append(
            f'- "{p.get("name", "")}" (host={bool(p.get("is_host") or p.get("is_tenant"))}, '
            f'joined={p.get("joined_at")}, left={p.get("left_at")})'
        )
    elapsed = _elapsed_minutes(recall_bot)
    return (
        "You judge whether a job interview has reached its END.\n\n"
        f"Known candidate name: \"{recall_bot.get('candidate_name') or 'unknown'}\"\n"
        f"Elapsed since bot joined: {elapsed if elapsed is not None else 'unknown'} min\n"
        f"This check was triggered by: {trigger}\n\n"
        "Participant timeline:\n"
        f"{chr(10).join(timeline) or '- (none)'}\n\n"
        "Transcript so far (speaker-attributed, oldest first):\n"
        f"{transcript_text or '(no speech captured)'}\n\n"
        "Decide the phase:\n"
        "- early: greetings / setup, interview just started\n"
        "- mid: interview in progress (questions being asked/answered)\n"
        "- wrapping_up: closing signals — 'any questions for me?', 'thanks for "
        "your time', 'we'll be in touch', goodbyes\n"
        "- ended: clearly over; OR the candidate never joined and the "
        "interviewer is dictating a verdict / saying the candidate no-showed\n\n"
        "Also decide is_no_show: true if the candidate never meaningfully "
        "participated (e.g. only the host/interviewer spoke).\n\n"
        "A momentary drop early in the interview (e.g. a screen-share glitch) "
        "is NOT the end — return mid.\n\n"
        "Return JSON only:\n"
        '{"phase": "early|mid|wrapping_up|ended", "confidence": <0.0-1.0>, '
        '"is_no_show": <true|false>, "reasoning": "<brief>"}'
    )


async def _llm_judge(prompt: str, settings, llm=None) -> Optional[dict]:
    """One-shot gateway call. Returns the parsed dict or None on any failure.

    `llm` defaults to the gateway client and is a parameter so tests can pass
    llm-core's FakeLLM. This site POSTed raw httpx straight to the provider's
    messages endpoint until phase 8; because it imported no SDK, every
    provider-surface test passed while it was still egressing directly.
    """
    if llm is None:
        from app.dependencies import get_llm_client

        llm = get_llm_client()
    try:
        started = time.monotonic()
        reply = await llm.complete(
            model=settings.END_STATE_MODEL,
            max_tokens=256,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        content = reply.text or ""
        logger.info(
            "llm_response",
            extra={
                "event": "llm_response",
                "model": settings.END_STATE_MODEL,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
        )
        result = parse_json_response(content)
        if not isinstance(result, dict) or "phase" not in result:
            logger.warning(f"end-state: bad LLM shape: {content}")
            return None
        return result
    except Exception as e:
        logger.error(f"end-state: LLM call failed: {e}")
        return None
