"""Shared pipeline runner used by both the production Lambda handler and
the local replay script. Bypasses Supabase by taking all inputs as
in-memory dicts.
"""
from __future__ import annotations

from typing import Any


async def run_pipeline_for_inputs(
    feedback_source: dict[str, Any],
    questions: list[dict[str, Any]],
    role_context: dict[str, Any],
    transcript: dict[str, Any],
    processor,  # type: JobProcessor — left untyped to avoid import cycles in tests
) -> dict[str, Any]:
    """Dispatch to the right pipeline branch and return its result dict.

    Args:
        feedback_source: {"source": "scorecard"|"bot"|"none", optional "scorecard_transcript",
                          "has_interview_transcript": bool}
        questions: list of {id, question_number, heading, description}
        role_context: dict accepted by JobProcessor.process_from_*
        transcript: {"segments": list[dict], "feedback_transcript": str,
                     "feedback_start_timestamp": float | None}
        processor: a JobProcessor instance (real or mock)

    Returns:
        The dict returned by the processor: keys complete_result, evidence_result,
        judge_result, summary_result (all model_dump shapes).
    """
    source = feedback_source.get("source")
    segments = transcript.get("segments") or []

    if source == "scorecard":
        segments_list = transcript.get("segments") or []
        # Match prior handler behavior exactly: None when empty, not [].
        interview_segments = segments_list if (
            feedback_source.get("has_interview_transcript") and segments_list
        ) else None
        return await processor.process_from_scorecard(
            scorecard_text=feedback_source.get("scorecard_transcript") or "",
            questions=questions,
            role_context=role_context,
            interview_segments=interview_segments,
        )

    # source == "bot" or "none" — both fall through to segment-based processing
    # (matches handler.py current behavior at lines 90-105).
    return await processor.process_from_segments(
        segments=segments,
        feedback_start_timestamp=transcript.get("feedback_start_timestamp"),
        questions=questions,
        role_context=role_context,
    )
