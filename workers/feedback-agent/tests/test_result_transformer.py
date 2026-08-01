"""Tests for the T_OVERALL persistence fix and the post-bypass shape.

These tests assume Task 1.7 (drop-bug fix) and Task 1.9 (judge bypass) both
ship in PR 1. After Task 1.9, T_OVERALL bullets bypass evidence + judge
entirely and arrive in result_transformer via `summary_result.overall_feedback`,
not `judge_result.judged_feedback`.
"""
import pytest

from src.jobs.result_transformer import transform_to_feedback_output


def _summary_with_overall():
    return {
        "question_summaries": [
            {"topic_id": "T1", "topic_heading": "B2B",
             "summary": "competent.", "evidence_status": "supported",
             "sentiment": "positive"},
        ],
        "round_summary": "fine round.",
        "competency_snapshots": "- X: Y",
        "round_rating": "yes",
        "overall_feedback": [
            {"feedback_data": "good fit for the team",
             "evidence": [],
             "evidence_status": "holistic"},
        ],
    }


def _judged_questions_only():
    return {
        "judged_feedback": [
            {
                "topic_id": "T1", "topic_heading": "B2B",
                "feedback": "specific claim", "sentiment": "positive",
                "evidence_status": "supported", "evidence": ["e1"],
                "reasoning": "...",
            },
        ],
    }


def test_overall_feedback_is_always_preserved_when_present():
    out = transform_to_feedback_output(_judged_questions_only(), _summary_with_overall())
    assert "overall_feedback" in out
    assert len(out["overall_feedback"]) == 1
    assert out["overall_feedback"][0]["feedback_data"] == "good fit for the team"


def test_overall_feedback_is_empty_list_when_no_overall_items():
    summary = _summary_with_overall()
    summary["overall_feedback"] = []
    out = transform_to_feedback_output(_judged_questions_only(), summary)
    assert out.get("overall_feedback") == []


def test_questions_are_still_populated_when_overall_present():
    out = transform_to_feedback_output(_judged_questions_only(), _summary_with_overall())
    feedback_questions = out["feedback_questions"]
    q1 = next(q for q in feedback_questions if q["question_number"] == 1)
    assert q1["feedback"][0]["feedback_data"] == "specific claim"
