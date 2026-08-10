"""Stage 4: LLM synthesis of 9 prefilled answers."""

from __future__ import annotations

import json
from typing import Any

import structlog

from ._fence import strip_markdown_fence
from ..prompts.synthesize_9_answers import (
    SYNTHESIZE_SYSTEM_PROMPT,
    build_synthesize_user_prompt,
)

logger = structlog.get_logger(__name__)

QUESTION_IDS = [
    "q1_role_overview", "q2_rounds", "q3_focus_areas", "q4_must_haves",
    "q5_nice_to_haves", "q6_cultural_fit", "q7_team_structure",
    "q8_red_flags", "q9_anything_else",
]

VALID_CONFIDENCE = {"none", "low", "medium", "high"}


def _empty_answers() -> dict[str, Any]:
    return {qid: {"text": None, "extraction_confidence": "none", "sources": []} for qid in QUESTION_IDS}


def _normalize_answer(answer: Any) -> dict:
    """Coerce one answer entry into the expected shape. Drops or replaces malformed fields."""
    if not isinstance(answer, dict):
        return {"text": None, "extraction_confidence": "none", "sources": []}

    # text: str or None
    text = answer.get("text")
    if text is not None and not isinstance(text, str):
        text = str(text)

    # Defensive rename: fold 'confidence' → 'extraction_confidence' if missing
    if "extraction_confidence" not in answer and "confidence" in answer:
        answer = {**answer, "extraction_confidence": answer["confidence"]}
    conf = answer.get("extraction_confidence", "none")
    if not isinstance(conf, str) or conf not in VALID_CONFIDENCE:
        conf = "none"

    # sources: must be list of strings
    sources = answer.get("sources", [])
    if not isinstance(sources, list):
        sources = []
    else:
        sources = [str(s) for s in sources if s is not None]

    return {"text": text, "extraction_confidence": conf, "sources": sources}


async def synthesize_answers(
    llm: Any,
    model: str,
    form_data: dict[str, Any],
    jd_facts: dict[str, Any],
    cortex_data: dict[str, Any],
) -> dict[str, Any]:
    reply = await llm.complete(
        model=model,
        max_tokens=4096,
        temperature=0,
        system=SYNTHESIZE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_synthesize_user_prompt(form_data, jd_facts, cortex_data)}],
    )
    raw = (reply.text or "").strip()
    raw = strip_markdown_fence(raw)

    # Every degraded path below returns _empty_answers(), which pipeline.py writes
    # to BOTH prefilled_answers AND current_answers — so it becomes the session's
    # starting context. That shape is deliberately kept (a failure here must not
    # break the intake), but each path gets its OWN log line: "the model returned
    # nothing", "the model returned prose we could not parse" and "the model
    # returned a non-object" have different causes and different fixes, and
    # without this they were indistinguishable from each other AND from a JD that
    # genuinely yielded nothing.
    if not raw:
        logger.warning("synthesize_empty_reply", alias=model)
        return _empty_answers()

    try:
        answers = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("synthesize_unparseable", raw=raw[:500])
        return _empty_answers()

    if not isinstance(answers, dict):
        logger.warning("synthesize_not_an_object", kind=type(answers).__name__)
        return _empty_answers()

    normalized = {}
    for qid in QUESTION_IDS:
        normalized[qid] = _normalize_answer(answers.get(qid))
    return normalized


