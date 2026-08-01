"""Coverage tracker prompt + JSON patch parser (spec section 7)."""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from intake_core.questions import INTAKE_QUESTIONS

logger = structlog.get_logger(__name__)

_VALID_QIDS = {q["id"] for q in INTAKE_QUESTIONS}
_VALID_STATUS = {"untouched", "needs_probe", "discussed", "validated", "skipped"}
_VALID_CONFIDENCE = {"none", "low", "medium", "high"}


TRACKER_SYSTEM_PROMPT = """You are a silent state tracker for an intake interview.

You read the current per-question state, the LATEST user turn, and the recent
context, and emit a JSON patch that updates current_answers for any questions
the user just addressed.

OUTPUT FORMAT: ONLY a JSON object. No prose. No markdown fences. Just the object.

PATCH SHAPE (only include questions the user actually addressed in the latest turn):
{
  "q4_must_haves": {
    "status": "discussed",
    "extraction_confidence": "medium",
    "text": "Python, Postgres, also Kafka per latest mention"
  }
}

VALID STATUS: untouched | needs_probe | discussed | validated | skipped
VALID CONFIDENCE: none | low | medium | high
VALID QIDS: q1_role_overview, q2_rounds, q3_focus_areas, q4_must_haves,
            q5_nice_to_haves, q6_cultural_fit, q7_team_structure,
            q8_red_flags, q9_anything_else

RULES:
- If the user said "skip" / "don't know" for a specific question, emit
  {"<qid>": {"status": "skipped"}}.
- If the user contributed NEW text, include the consolidated text (don't repeat
  the old text — write what should now be stored).
- If the user did NOT address any question in the latest turn, return {} (empty).
- Be conservative. Better to return {} than to write speculative state.
"""


def build_tracker_prompt(
    current_answers: dict[str, Any],
    last_user_turn: str,
    recent_turns: list[dict[str, Any]],
) -> str:
    return (
        f"CURRENT STATE:\n{json.dumps(current_answers, indent=2)}\n\n"
        f"RECENT CONTEXT (last 3 turns):\n{_format_turns(recent_turns)}\n\n"
        f"LATEST USER TURN:\n{last_user_turn}\n\n"
        f"Output the JSON patch object now."
    )


def _format_turns(turns: list[dict[str, Any]]) -> str:
    if not turns:
        return "(no prior turns)"
    lines = []
    for t in turns[-3:]:
        role = t.get("role", "?")
        content = (t.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"[{role}] {content}")
    return "\n".join(lines) if lines else "(no prior turns)"


_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def parse_tracker_response(raw: str) -> dict[str, Any]:
    """Parse the tracker LLM response into a validated patch dict.

    Strips markdown fences, ignores prose noise, drops unknown qids/statuses/confidences.
    Returns {} on any parse failure.
    """
    if not raw:
        return {}
    text = raw.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("tracker_parse_failed", raw_sample=raw[:200])
        return {}

    if not isinstance(data, dict):
        return {}

    cleaned: dict[str, Any] = {}
    for qid, entry in data.items():
        if qid not in _VALID_QIDS or not isinstance(entry, dict):
            continue
        clean_entry: dict[str, Any] = {}
        if "status" in entry:
            if entry["status"] in _VALID_STATUS:
                clean_entry["status"] = entry["status"]
            else:
                continue  # whole entry invalid
        if "extraction_confidence" in entry:
            if entry["extraction_confidence"] in _VALID_CONFIDENCE:
                clean_entry["extraction_confidence"] = entry["extraction_confidence"]
            else:
                continue
        if "text" in entry:
            if isinstance(entry["text"], str):
                clean_entry["text"] = entry["text"]
        if clean_entry:
            cleaned[qid] = clean_entry
    return cleaned
