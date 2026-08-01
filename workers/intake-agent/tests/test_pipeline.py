"""Pipeline test for v2 intake-agent. Mocks Anthropic + Supabase client."""

from unittest.mock import AsyncMock, MagicMock, patch, call
import json
import pytest

from src.pipeline import IntakePipelineV2, format_current_answers_as_summary


def test_format_current_answers_as_summary_handles_full_set():
    current = {
        "q1_role_overview": {"text": "Builds payments infra"},
        "q2_rounds": {"text": "4 rounds"},
        "q3_focus_areas": {"text": "System design + coding"},
        "q4_must_haves": {"text": "Python, PG"},
        "q5_nice_to_haves": {"text": "Kafka"},
        "q6_cultural_fit": {"text": "directness, ownership"},
        "q7_team_structure": {"text": None},
        "q8_red_flags": {"text": None},
        "q9_anything_else": {"text": None},
    }
    questions_snapshot = [
        {"id": "q1_role_overview", "topic": "Role Overview", "order": 1},
        {"id": "q2_rounds", "topic": "Interview Rounds", "order": 2},
        {"id": "q3_focus_areas", "topic": "Interview Focus Areas", "order": 3},
        {"id": "q4_must_haves", "topic": "Must-Have Skills", "order": 4},
        {"id": "q5_nice_to_haves", "topic": "Nice-to-Have Skills", "order": 5},
        {"id": "q6_cultural_fit", "topic": "Cultural Fit", "order": 6},
        {"id": "q7_team_structure", "topic": "Team Structure", "order": 7},
        {"id": "q8_red_flags", "topic": "Red Flags", "order": 8},
        {"id": "q9_anything_else", "topic": "Anything Else", "order": 9},
    ]
    out = format_current_answers_as_summary(current, questions_snapshot)
    assert "Role Overview" in out
    assert "Builds payments infra" in out
    assert "Kafka" in out
    # Empty answers should not contribute clutter
    assert "Team Structure" not in out or "no answer" in out.lower()


def test_format_current_answers_handles_missing_keys():
    out = format_current_answers_as_summary({}, [
        {"id": "q1_role_overview", "topic": "Role Overview", "order": 1}
    ])
    assert isinstance(out, str)


@pytest.mark.asyncio
async def test_pipeline_writes_rounds_and_feedback_questions():
    anthropic = AsyncMock()
    # call_sonnet returns: first for rounds, then once per round for details
    anthropic.call_sonnet.side_effect = [
        json.dumps({
            "rounds": [
                {"name": "Coding", "category": "coding", "duration_minutes": 60,
                 "description": "Live coding", "skills": ["Python"]},
                {"name": "System Design", "category": "design", "duration_minutes": 60,
                 "description": "Whiteboard design", "skills": ["distributed systems"]},
            ]
        }),
        json.dumps({
            "guidelines": [{"title": "Be specific", "description": "Push for code, not pseudo"}],
            "feedback_questions": [
                {"heading": "Code Quality", "description": "Readable, structured."},
                {"heading": "Problem Solving", "description": "Decomposes correctly."},
                {"heading": "Communication", "description": "Talks through approach."},
            ]
        }),
        json.dumps({
            "guidelines": [{"title": "Use real systems", "description": "Existing infra ok"}],
            "feedback_questions": [
                {"heading": "Trade-offs", "description": "Considers consistency vs availability."},
                {"heading": "Scale Reasoning", "description": "Estimates QPS sanely."},
                {"heading": "Clarification", "description": "Asks before assuming."},
            ]
        }),
    ]

    supabase = MagicMock()
    supabase.save_round_skeletons = AsyncMock(return_value=["round-1", "round-2"])
    supabase.save_round_details = AsyncMock()
    supabase.finalize_interview_plan = AsyncMock()

    role_context = {
        "session_id": "s1",
        "requisition_id": "r1",
        "organization_id": "o1",
        "role_title": "Senior BE",
        "experience_min_years": 5,
        "experience_max_years": 8,
        "role_location": "NYC",
        "intake_summary_struct": {
            "q1_role_overview": {"text": "Payments infra lead"},
            "q4_must_haves": {"text": "Python, PG"},
        },
        "turns": [],
        "modalities_used": ["voice"],
        "duration_min": 5,
        "questions_version": "v1-2026-05-27",
        "questions_snapshot": [
            {"id": "q1_role_overview", "topic": "Role Overview", "order": 1},
            {"id": "q4_must_haves", "topic": "Must-Have Skills", "order": 4},
        ],
    }

    pipeline = IntakePipelineV2(anthropic=anthropic, supabase=supabase, session_id="s1")
    await pipeline.run(role_context)

    # 2 rounds inserted
    supabase.save_round_skeletons.assert_awaited_once()
    rounds_arg = supabase.save_round_skeletons.await_args.args[1]
    assert len(rounds_arg) == 2
    assert rounds_arg[0]["name"] == "Coding"

    # save_round_details called once per round
    assert supabase.save_round_details.await_count == 2

    # finalize_interview_plan called with composed artifact
    supabase.finalize_interview_plan.assert_awaited_once()
    finalize_kwargs = supabase.finalize_interview_plan.await_args.kwargs
    assert finalize_kwargs["session_id"] == "s1"
    assert finalize_kwargs["requisition_id"] == "r1"
    assert finalize_kwargs["organization_id"] == "o1"
    plan = finalize_kwargs["interview_plan"]
    assert plan["round_count"] == 2
    assert len(plan["rounds"]) == 2
    assert plan["rounds"][0]["feedback_questions"][0]["heading"] == "Code Quality"


@pytest.mark.asyncio
async def test_finalize_interview_plan_publishes_cortex_schema():
    """SQS body must include source_id/org_id/last_touch_at/event_pk — the fields
    the Cortex SQS consumer reads via body["source_id"] etc. Publishing the old
    session_id/organization_id fields caused KeyError → DLQ (May 2026 regression).
    """
    from src.clients.supabase import SupabaseClient

    captured_bodies = []

    def fake_publish(event_type: str, data: dict) -> None:
        captured_bodies.append({"event_type": event_type, **data})

    with patch("httpx.AsyncClient") as MockClient:
        mock_http = AsyncMock()
        mock_http.patch = AsyncMock(return_value=MagicMock(json=MagicMock(return_value={})))
        MockClient.return_value = mock_http

        client = SupabaseClient.__new__(SupabaseClient)
        client.url = "http://fake"
        client.headers = {}
        client._publish_sqs_event = fake_publish

        await client.finalize_interview_plan(
            session_id="sess-abc",
            requisition_id="req-xyz",
            organization_id="org-123",
            interview_plan={"round_count": 0, "rounds": []},
        )

    assert len(captured_bodies) == 1
    body = captured_bodies[0]
    assert body["event_type"] == "intake_v2_completed"
    assert body["source_id"] == "sess-abc", "source_id must be session_id"
    assert body["org_id"] == "org-123", "org_id must match organization_id"
    assert "last_touch_at" in body, "last_touch_at required by Cortex consumer"
    assert "event_pk" in body, "event_pk (idempotency key) required by Cortex consumer"
    assert "requisition_id" in body, "requisition_id kept for downstream handler context"
    # Old wrong field names must NOT be present
    assert "session_id" not in body, "session_id must be renamed to source_id"
    assert "organization_id" not in body, "organization_id must be renamed to org_id"


@pytest.mark.asyncio
async def test_save_round_skeletons_rejects_non_list_body():
    """A non-list PostgREST insert response (error object / unexpected shape) must
    raise a descriptive ValueError — never a bare KeyError(0), which stringifies to
    a contextless process_error='0' that strands the session (the loop incident)."""
    from src.clients.supabase import SupabaseClient

    mock_http = AsyncMock()
    mock_http.request = AsyncMock(return_value=MagicMock(raise_for_status=MagicMock()))
    # PostgREST returns a dict here, not the expected [{...}] list of inserted rows.
    mock_http.post = AsyncMock(
        return_value=MagicMock(
            raise_for_status=MagicMock(),
            json=MagicMock(return_value={"code": "PGRST", "message": "nope"}),
        )
    )

    with patch("src.clients.supabase.get_async_http_client", return_value=mock_http):
        client = SupabaseClient.__new__(SupabaseClient)
        client.url = "http://fake"
        client.headers = {}
        with pytest.raises(ValueError) as exc:
            await client.save_round_skeletons(
                "req-1", [{"name": "Tech Screen", "category": "technical", "skills": ["x"]}]
            )

    assert str(exc.value) != "0", "must not surface a bare KeyError(0)"
    assert "unexpected insert response" in str(exc.value)


@pytest.mark.asyncio
async def test_pipeline_propagates_errors_from_rounds_call():
    anthropic = AsyncMock()
    anthropic.call_sonnet.side_effect = ValueError("LLM 500")
    supabase = MagicMock()
    pipeline = IntakePipelineV2(anthropic=anthropic, supabase=supabase, session_id="s1")
    role_context = {
        "session_id": "s1", "requisition_id": "r1", "organization_id": "o1",
        "role_title": "x", "experience_min_years": 0, "experience_max_years": 2,
        "role_location": "x", "intake_summary_struct": {}, "turns": [],
        "modalities_used": [], "duration_min": 0, "questions_version": "v1",
        "questions_snapshot": [],
    }
    with pytest.raises(ValueError):
        await pipeline.run(role_context)
