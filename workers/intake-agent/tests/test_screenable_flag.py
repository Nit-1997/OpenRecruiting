"""Screening-agent Phase 1, Task 2: per-round `openrecruiting_screenable` eligibility flag.

Asserts (1) the rounds-skeleton JSON schema + prompt advertise the new fields, and
(2) the pipeline carries `openrecruiting_screenable` / `openrecruiting_screenable_reason` through from a
round skeleton into the interview_plan artifact, defaulting safely when absent.
"""

from unittest.mock import AsyncMock, MagicMock
import json
import pytest

from src.pipeline import IntakePipelineV2, round_skeleton_to_artifact
from src.prompts import ROUNDS_JSON_SCHEMA, build_rounds_prompt


def test_rounds_schema_advertises_screenable_fields():
    assert "openrecruiting_screenable" in ROUNDS_JSON_SCHEMA
    assert "boolean" in ROUNDS_JSON_SCHEMA  # openrecruiting_screenable typed as boolean
    assert "openrecruiting_screenable_reason" in ROUNDS_JSON_SCHEMA


def test_rounds_prompt_instructs_screenable_classification():
    prompt = build_rounds_prompt(intake_summary="Role: X\nExperience: 3+ years")
    assert "openrecruiting_screenable" in prompt
    assert "openrecruiting_screenable_reason" in prompt


def test_artifact_mapping_carries_screenable_through():
    skeleton = {
        "name": "Recruiter Screen",
        "category": "behavioral",
        "duration_minutes": 30,
        "description": "Conversational screen",
        "skills": ["communication"],
        "openrecruiting_screenable": True,
        "openrecruiting_screenable_reason": "Conversational, question-driven screen.",
    }
    details = {"guidelines": [], "feedback_questions": []}
    artifact = round_skeleton_to_artifact("round-1", skeleton, details, 0)

    assert artifact["openrecruiting_screenable"] is True
    assert artifact["openrecruiting_screenable_reason"] == "Conversational, question-driven screen."


def test_artifact_mapping_defaults_when_screenable_absent():
    skeleton = {
        "name": "Live Coding",
        "category": "coding",
        "duration_minutes": 60,
        "description": "Pair programming",
        "skills": ["python"],
    }
    details = {"guidelines": [], "feedback_questions": []}
    artifact = round_skeleton_to_artifact("round-2", skeleton, details, 1)

    assert artifact["openrecruiting_screenable"] is False
    assert artifact["openrecruiting_screenable_reason"] == ""


@pytest.mark.asyncio
async def test_pipeline_carries_screenable_into_interview_plan():
    anthropic = AsyncMock()
    anthropic.call_sonnet.side_effect = [
        json.dumps({
            "rounds": [
                {"name": "Recruiter Screen", "category": "behavioral", "duration_minutes": 30,
                 "description": "Conversational screen", "skills": ["communication"],
                 "openrecruiting_screenable": True, "openrecruiting_screenable_reason": "Voice-runnable Q&A."},
                {"name": "Live Coding", "category": "coding", "duration_minutes": 60,
                 "description": "Pair programming", "skills": ["python"]},
            ]
        }),
        json.dumps({
            "guidelines": [{"title": "Probe", "description": "Ask follow-ups"}],
            "feedback_questions": [
                {"heading": "Communication", "description": "Clear and concise."},
                {"heading": "Motivation", "description": "Genuine interest."},
                {"heading": "Fit", "description": "Aligns with role."},
            ],
        }),
        json.dumps({
            "guidelines": [{"title": "Code", "description": "Push for real code"}],
            "feedback_questions": [
                {"heading": "Code Quality", "description": "Readable, structured."},
                {"heading": "Problem Solving", "description": "Decomposes correctly."},
                {"heading": "Communication", "description": "Talks through approach."},
            ],
        }),
    ]

    supabase = MagicMock()
    supabase.save_round_skeletons = AsyncMock(return_value=["round-1", "round-2"])
    supabase.save_round_details = AsyncMock()
    supabase.finalize_interview_plan = AsyncMock()

    role_context = {
        "session_id": "s1", "requisition_id": "r1", "organization_id": "o1",
        "role_title": "Senior BE", "experience_min_years": 5, "experience_max_years": 8,
        "role_location": "NYC", "intake_summary_struct": {"q1": {"text": "infra"}},
        "turns": [], "modalities_used": ["voice"], "duration_min": 5,
        "questions_version": "v1", "questions_snapshot": [{"id": "q1", "topic": "Role", "order": 1}],
    }

    pipeline = IntakePipelineV2(anthropic=anthropic, supabase=supabase, session_id="s1")
    await pipeline.run(role_context)

    plan = supabase.finalize_interview_plan.await_args.kwargs["interview_plan"]
    rounds = plan["rounds"]
    assert rounds[0]["openrecruiting_screenable"] is True
    assert rounds[0]["openrecruiting_screenable_reason"] == "Voice-runnable Q&A."
    # Absent in skeleton → defaults applied
    assert rounds[1]["openrecruiting_screenable"] is False
    assert rounds[1]["openrecruiting_screenable_reason"] == ""
