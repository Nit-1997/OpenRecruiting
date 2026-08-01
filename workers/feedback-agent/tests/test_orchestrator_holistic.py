"""Tests for T_OVERALL routing change — bullets bypass evidence + judge."""
from unittest.mock import MagicMock

import pytest

from src.models.pydantic_models import (
    FeedbackItem,
    RoleContext,
    SummaryResult,
    TopicInput,
)


@pytest.mark.asyncio
async def test_t_overall_items_do_not_reach_judge(monkeypatch):
    """T_OVERALL FeedbackItems must be partitioned out before judge_feedback runs."""
    from src.services.orchestrator import FeedbackOrchestrator

    orch = FeedbackOrchestrator()

    captured = {}

    async def fake_process_complete(*a, **kw):
        rv = MagicMock()
        rv.chunk_map = {}
        rv.topic_map = {"T1": MagicMock(), "T_OVERALL": MagicMock()}
        rv.topic_chunk_map = {"T1": [], "T_OVERALL": []}
        rv.topic_feedback_map = {
            "T1": [FeedbackItem(feedback="t1 claim", antifeedback="t1 not", sentiment="positive")],
            "T_OVERALL": [FeedbackItem(feedback="good fit", antifeedback="poor fit", sentiment="positive")],
        }
        return rv

    async def fake_extract_evidence(chunk_map, topic_map, topic_chunk_map, topic_feedback_map, role_context):
        captured["evidence_topic_feedback_map"] = topic_feedback_map
        rv = MagicMock()
        rv.enriched_feedback = []
        return rv

    async def fake_judge_feedback(enriched_feedback, role_context):
        captured["judge_topics"] = [e.topic_id for e in enriched_feedback]
        rv = MagicMock()
        rv.judged_feedback = []
        return rv

    async def fake_generate_summaries(judged_feedback, **kwargs):
        captured["summary_holistic_notes"] = kwargs.get("holistic_notes")
        captured["summary_verbal_verdict"] = kwargs.get("verbal_verdict")
        return SummaryResult(
            question_summaries=[], round_summary="", competency_snapshots="",
            round_rating="maybe",
        )

    async def fake_extract_verdict(transcript):
        rv = MagicMock()
        rv.primary_rating = "yes"
        return rv

    monkeypatch.setattr(orch, "process_complete", fake_process_complete)
    monkeypatch.setattr(orch, "extract_evidence", fake_extract_evidence)
    monkeypatch.setattr(orch, "judge_feedback", fake_judge_feedback)
    monkeypatch.setattr(orch, "generate_summaries", fake_generate_summaries)
    monkeypatch.setattr(orch.verdict_service, "extract_verdict", fake_extract_verdict)

    await orch.process_full_pipeline(
        interview_transcript="", feedback_transcript="",
        topics=[TopicInput(heading="B2B", description="d")],
        role_context=RoleContext(),
    )

    # Evidence stage received only T1, not T_OVERALL:
    assert "T_OVERALL" not in captured["evidence_topic_feedback_map"]
    assert "T1" in captured["evidence_topic_feedback_map"]

    # Summary stage received the holistic notes and the verdict:
    holistic = captured["summary_holistic_notes"]
    assert holistic is not None
    assert len(holistic) == 1
    assert holistic[0].feedback == "good fit"

    assert captured["summary_verbal_verdict"] == "yes"
