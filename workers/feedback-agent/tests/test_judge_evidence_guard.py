"""A feedback item may not be marked 'supported' by nothing.

Two upstream failures compound. services/evidence.py catches Exception and
returns EMPTY evidence lists without raising, and services/judge.py's own
except-branch defaults `choice` to "feedback". A run where both LLM calls failed
therefore produced evidence_status="supported" with evidence=[] — a claim about a
real candidate, on a real scorecard, evidenced by nothing and indistinguishable
from a well-evidenced item.

Pre-existing and independent of the gateway migration; found while migrating
these call sites.
"""
from unittest.mock import AsyncMock

import pytest

from src.models import EnrichedFeedbackItem, RoleContext
from src.services.judge import JudgeService


def _item(feedback_evidence):
    return EnrichedFeedbackItem(
        topic_id="t1",
        topic_heading="Communication",
        feedback="Explains trade-offs clearly.",
        antifeedback="",
        sentiment="positive",
        feedback_evidence=feedback_evidence,
        antifeedback_evidence=[],
        reasoning="",
    )


def _role():
    return RoleContext(
        role_title="Backend Engineer",
        experience_range="5-8",
        must_have_skills=["Python"],
        good_to_have_skills=[],
        intake_notes="",
    )


@pytest.mark.asyncio
async def test_a_failed_judge_with_no_evidence_is_not_supported():
    """Both LLM calls failed: evidence came back empty, and the judge's own
    except-branch defaults to 'feedback'. The verdict must not claim support."""
    client = AsyncMock()
    client.call_sonnet.side_effect = RuntimeError("gateway down")

    judged = await JudgeService()._judge_single_feedback(_item([]), _role(), client)

    assert judged.evidence_status == "none", "supported requires evidence to point at"
    assert judged.evidence == []


@pytest.mark.asyncio
async def test_a_real_verdict_with_evidence_is_still_supported():
    """The guard must not swallow the healthy path."""
    client = AsyncMock()
    client.call_sonnet.return_value = '{"choice": "feedback", "reasoning": "clear"}'

    judged = await JudgeService()._judge_single_feedback(
        _item(["said X in round 2"]), _role(), client
    )

    assert judged.evidence_status == "supported"
    assert judged.evidence == ["said X in round 2"]
