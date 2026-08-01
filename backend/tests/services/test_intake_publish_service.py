"""Tests for IntakePublishService."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.intake_publish_service import (
    IntakePublishService,
    IntakePublishError,
)


@pytest.fixture
def mock_supabase():
    client = MagicMock()
    client.table.return_value = client
    client.select.return_value = client
    client.eq.return_value = client
    client.in_.return_value = client
    client.single.return_value = client
    client.update.return_value = client
    client.delete.return_value = client
    client.insert.return_value = client
    client.execute = MagicMock()
    client.execute_async = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_publish_valid_plan_flips_status(mock_supabase):
    sid, rid, uid, oid = uuid4(), uuid4(), uuid4(), uuid4()
    plan = {
        "version": "v1",
        "round_count": 1,
        "rounds": [{
            "round_id": str(uuid4()),
            "name": "Coding", "category": "coding",
            "duration_minutes": 60, "skills": ["Python"],
            "round_number": 1,
            "guidelines": [{"title": "x", "description": "y"}],
            "feedback_questions": [
                {"heading": "Code Quality", "description": "Read."},
                {"heading": "Problem Solving", "description": "Decompose."},
                {"heading": "Communication", "description": "Talk."},
            ],
        }],
    }
    mock_supabase.execute_async.side_effect = [
        MagicMock(data={"id": str(sid), "status": "submitted", "requisition_id": str(rid), "interview_plan": plan}),
        # delete existing rounds
        MagicMock(data=[]),
        # insert round — dict shape (production SupabaseAdminClient)
        MagicMock(data={"id": "new-round-1"}),
        # insert 3 feedback_questions
        MagicMock(data={"id": "fq-1"}),
        MagicMock(data={"id": "fq-2"}),
        MagicMock(data={"id": "fq-3"}),
        # update requisitions.status='planned'
        MagicMock(data={"id": str(rid)}),
        # update intake_sessions.status='published'
        MagicMock(data={"id": str(sid)}),
    ]
    svc = IntakePublishService(supabase_client=mock_supabase)
    result = await svc.publish(session_id=sid, user_id=uid, organization_id=oid)
    assert result["requisition_id"] == str(rid)
    assert result["redirect_url"] == f"/view/roles/{rid}"


@pytest.mark.asyncio
async def test_publish_valid_plan_list_shape(mock_supabase):
    """Ensure publish also works when insert returns list shape (supabase-py / test mocks)."""
    sid, rid, uid, oid = uuid4(), uuid4(), uuid4(), uuid4()
    plan = {
        "rounds": [{
            "name": "Screening", "category": "hr",
            "duration_minutes": 30, "skills": [],
            "guidelines": [],
            "feedback_questions": [{"heading": "Culture Fit", "description": "Check."}],
        }],
    }
    mock_supabase.execute_async.side_effect = [
        MagicMock(data={"id": str(sid), "status": "submitted", "requisition_id": str(rid), "interview_plan": plan}),
        MagicMock(data=[]),
        # round insert — list shape
        MagicMock(data=[{"id": "round-list-1"}]),
        MagicMock(data=[{"id": "fq-list-1"}]),
        MagicMock(data=[{"id": str(rid)}]),
        MagicMock(data=[{"id": str(sid)}]),
    ]
    svc = IntakePublishService(supabase_client=mock_supabase)
    result = await svc.publish(session_id=sid, user_id=uid, organization_id=oid)
    assert result["requisition_id"] == str(rid)


@pytest.mark.asyncio
async def test_publish_rejects_unpublishable_session(mock_supabase):
    # 'ready' is neither 'submitted' nor 'published' → not in a publishable state.
    sid = uuid4()
    mock_supabase.execute_async.return_value = MagicMock(data={
        "id": str(sid), "status": "ready", "requisition_id": str(uuid4()), "interview_plan": None
    })
    svc = IntakePublishService(supabase_client=mock_supabase)
    with pytest.raises(IntakePublishError, match="not ready to publish"):
        await svc.publish(session_id=sid, user_id=uuid4(), organization_id=uuid4())


@pytest.mark.asyncio
async def test_publish_rejects_missing_plan(mock_supabase):
    sid = uuid4()
    mock_supabase.execute_async.return_value = MagicMock(data={
        "id": str(sid), "status": "submitted", "requisition_id": str(uuid4()), "interview_plan": None
    })
    svc = IntakePublishService(supabase_client=mock_supabase)
    with pytest.raises(IntakePublishError, match="interview_plan"):
        await svc.publish(session_id=sid, user_id=uuid4(), organization_id=uuid4())


@pytest.mark.asyncio
async def test_publish_cross_tenant_returns_404(mock_supabase):
    """When WHERE user_id+org_id filters match nothing, publish raises 404 IntakePublishError."""
    sid = uuid4()
    mock_supabase.execute_async.return_value = MagicMock(data=None)
    svc = IntakePublishService(supabase_client=mock_supabase)
    with pytest.raises(IntakePublishError) as exc:
        await svc.publish(session_id=sid, user_id=uuid4(), organization_id=uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_validate_plan_tolerates_screenable_fields():
    """A plan whose round carries ai_screenable / ai_screenable_reason
    must validate without error (Screening Agent Phase 1, Task 3)."""
    from app.services.intake_publish_service import _validate_plan

    plan = {
        "rounds": [{
            "name": "Recruiter Screen", "category": "screening",
            "ai_screenable": True,
            "ai_screenable_reason": "Conversational, question-driven screen.",
            "feedback_questions": [{"heading": "Motivation", "description": "Why us?"}],
        }],
    }
    # Should not raise.
    _validate_plan(plan)


@pytest.mark.asyncio
async def test_publish_persists_screenable_fields(mock_supabase):
    """The rounds insert payload carries ai_screenable + reason from the plan."""
    sid, rid, uid, oid = uuid4(), uuid4(), uuid4(), uuid4()
    plan = {
        "rounds": [{
            "name": "Recruiter Screen", "category": "screening",
            "duration_minutes": 30, "skills": [],
            "guidelines": [],
            "ai_screenable": True,
            "ai_screenable_reason": "Voice-runnable Q&A.",
            "feedback_questions": [{"heading": "Motivation", "description": "Why us?"}],
        }],
    }
    mock_supabase.execute_async.side_effect = [
        MagicMock(data={"id": str(sid), "status": "submitted", "requisition_id": str(rid), "interview_plan": plan}),
        MagicMock(data=[]),
        MagicMock(data={"id": "new-round-1"}),
        MagicMock(data={"id": "fq-1"}),
        MagicMock(data={"id": str(rid)}),
        MagicMock(data={"id": str(sid)}),
    ]
    svc = IntakePublishService(supabase_client=mock_supabase)
    await svc.publish(session_id=sid, user_id=uid, organization_id=oid)

    round_insert = next(
        c for c in mock_supabase.insert.call_args_list
        if "name" in (c.args[0] if c.args else {})
    )
    payload = round_insert.args[0]
    assert payload["ai_screenable"] is True
    assert payload["ai_screenable_reason"] == "Voice-runnable Q&A."


@pytest.mark.asyncio
async def test_publish_screenable_defaults_when_omitted(mock_supabase):
    """When the plan omits the fields, insert defaults to False / None."""
    sid, rid, uid, oid = uuid4(), uuid4(), uuid4(), uuid4()
    plan = {
        "rounds": [{
            "name": "Coding", "category": "coding",
            "duration_minutes": 60, "skills": ["Python"],
            "guidelines": [],
            "feedback_questions": [{"heading": "Code Quality", "description": "Read."}],
        }],
    }
    mock_supabase.execute_async.side_effect = [
        MagicMock(data={"id": str(sid), "status": "submitted", "requisition_id": str(rid), "interview_plan": plan}),
        MagicMock(data=[]),
        MagicMock(data={"id": "new-round-1"}),
        MagicMock(data={"id": "fq-1"}),
        MagicMock(data={"id": str(rid)}),
        MagicMock(data={"id": str(sid)}),
    ]
    svc = IntakePublishService(supabase_client=mock_supabase)
    await svc.publish(session_id=sid, user_id=uid, organization_id=oid)

    round_insert = next(
        c for c in mock_supabase.insert.call_args_list
        if "name" in (c.args[0] if c.args else {})
    )
    payload = round_insert.args[0]
    assert payload["ai_screenable"] is False
    assert payload["ai_screenable_reason"] is None


@pytest.mark.asyncio
async def test_validate_plan_tolerates_screening_object():
    """A plan whose round carries an optional `screening` object must validate
    without error and without being required (pre-publish screening config)."""
    from app.services.intake_publish_service import _validate_plan

    plan = {
        "rounds": [{
            "name": "Recruiter Screen", "category": "screening",
            "screening": {
                "enabled": True,
                "voice": "aura-luna-en",
                "questions": [
                    {"title": "Q1", "prompt": "P1", "order_index": 0},
                ],
            },
            "feedback_questions": [{"heading": "Motivation", "description": "Why us?"}],
        }],
    }
    # Should not raise.
    _validate_plan(plan)


@pytest.mark.asyncio
async def test_publish_materializes_screening(mock_supabase):
    """A round carrying screening.enabled=true (+ questions + persona_snapshot) must,
    after the round row is inserted, call screening_save_config with the NEW round_id
    and the artifact's questions, then persist the persona + attach it to the config."""
    sid, rid, uid, oid = uuid4(), uuid4(), uuid4(), uuid4()
    persona_snapshot = {
        "dimensions": [{"key": "tone_rapport", "value": "Warm", "confidence": 0.0, "source": "generic"}],
        "text": "Be warm and curious.",
    }
    plan = {
        "rounds": [{
            "name": "Recruiter Screen", "category": "screening",
            "duration_minutes": 30, "skills": [], "guidelines": [],
            "feedback_questions": [{"heading": "Motivation", "description": "Why us?"}],
            "screening": {
                "enabled": True,
                "voice": "aura-stella-en",
                "follow_up_style": "adaptive_probes",
                "validity_days": 14,
                "deploy_scope": "manual",
                "questions": [
                    {"title": "Toughest incident", "prompt": "Walk me through it.",
                     "probe": "Root cause?", "signal": "EXECUTION",
                     "dimension": "ownership", "duration_minutes": 6, "order_index": 0},
                ],
                "persona_snapshot": persona_snapshot,
            },
        }],
    }
    mock_supabase.execute_async.side_effect = [
        MagicMock(data={"id": str(sid), "status": "submitted", "requisition_id": str(rid), "interview_plan": plan}),
        MagicMock(data=[]),                       # delete existing rounds
        MagicMock(data={"id": "new-round-1"}),    # insert round
        MagicMock(data={"id": "fq-1"}),           # insert feedback question
        MagicMock(data={"id": str(rid)}),         # update requisitions
        MagicMock(data={"id": str(sid)}),         # update intake_sessions
        # --- screening materialization (AFTER rounds/questions committed) ---
        MagicMock(data={"id": "persona-row-1"}),  # insert personas row
        MagicMock(data=[{"id": "rsc-1"}]),        # update round_screening_configs.persona_*
    ]
    mock_supabase.rpc = AsyncMock(return_value=MagicMock(data={"config_id": "cfg-1"}))

    svc = IntakePublishService(supabase_client=mock_supabase)
    # Patch the ATS call_rpc so the (always-fired) promote/seed don't add awaits to
    # mock_supabase.rpc — screening uses supabase.rpc directly (await_count == 1).
    with patch("app.api.v2.core.rpc.call_rpc", new=AsyncMock(return_value=[])):
        await svc.publish(session_id=sid, user_id=uid, organization_id=oid)

    # The RPC was called once with the NEW round id + the artifact's questions.
    assert mock_supabase.rpc.await_count == 1
    name, params = mock_supabase.rpc.await_args.args
    assert name == "screening_save_config"
    payload = params["p"]
    assert payload["round_id"] == "new-round-1"
    assert payload["requisition_id"] == str(rid)
    assert payload["enabled"] is True
    assert payload["voice"] == "aura-stella-en"
    assert payload["validity_days"] == 14
    assert len(payload["questions"]) == 1
    assert payload["questions"][0]["title"] == "Toughest incident"
    assert payload["questions"][0]["order_index"] == 0

    # Persona persisted (personas insert) + attached to the new config (rsc update).
    insert_tables = [c.args[0] for c in mock_supabase.table.call_args_list]
    assert "personas" in insert_tables
    assert "round_screening_configs" in insert_tables
    persona_insert = next(
        c for c in mock_supabase.insert.call_args_list
        if "composed_text" in (c.args[0] if c.args else {})
    )
    assert persona_insert.args[0]["requisition_id"] == str(rid)


@pytest.mark.asyncio
async def test_publish_without_screening_does_not_materialize(mock_supabase):
    """A round with no `screening` object never touches the screening RPC/personas."""
    sid, rid, uid, oid = uuid4(), uuid4(), uuid4(), uuid4()
    plan = {
        "rounds": [{
            "name": "Coding", "category": "coding",
            "duration_minutes": 60, "skills": ["Python"], "guidelines": [],
            "feedback_questions": [{"heading": "Code Quality", "description": "Read."}],
        }],
    }
    mock_supabase.execute_async.side_effect = [
        MagicMock(data={"id": str(sid), "status": "submitted", "requisition_id": str(rid), "interview_plan": plan}),
        MagicMock(data=[]),
        MagicMock(data={"id": "new-round-1"}),
        MagicMock(data={"id": "fq-1"}),
        MagicMock(data={"id": str(rid)}),
        MagicMock(data={"id": str(sid)}),
    ]
    mock_supabase.rpc = AsyncMock()

    svc = IntakePublishService(supabase_client=mock_supabase)
    # ATS promote always fires; patch call_rpc so it doesn't touch supabase.rpc.
    with patch("app.api.v2.core.rpc.call_rpc", new=AsyncMock(return_value=[])):
        await svc.publish(session_id=sid, user_id=uid, organization_id=oid)

    mock_supabase.rpc.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_screening_disabled_does_not_materialize(mock_supabase):
    """screening present but enabled=false is a no-op (config stays off pre-publish)."""
    sid, rid, uid, oid = uuid4(), uuid4(), uuid4(), uuid4()
    plan = {
        "rounds": [{
            "name": "Coding", "category": "coding",
            "duration_minutes": 60, "skills": [], "guidelines": [],
            "feedback_questions": [{"heading": "Code Quality", "description": "Read."}],
            "screening": {"enabled": False, "questions": [{"title": "Q", "prompt": "P"}]},
        }],
    }
    mock_supabase.execute_async.side_effect = [
        MagicMock(data={"id": str(sid), "status": "submitted", "requisition_id": str(rid), "interview_plan": plan}),
        MagicMock(data=[]),
        MagicMock(data={"id": "new-round-1"}),
        MagicMock(data={"id": "fq-1"}),
        MagicMock(data={"id": str(rid)}),
        MagicMock(data={"id": str(sid)}),
    ]
    mock_supabase.rpc = AsyncMock()

    svc = IntakePublishService(supabase_client=mock_supabase)
    # ATS promote always fires; patch call_rpc so it doesn't touch supabase.rpc.
    with patch("app.api.v2.core.rpc.call_rpc", new=AsyncMock(return_value=[])):
        await svc.publish(session_id=sid, user_id=uid, organization_id=oid)

    mock_supabase.rpc.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_screening_failure_is_resilient(mock_supabase):
    """If screening materialization fails, the publish still succeeds (the round is
    already committed; screening can be re-added on the dashboard)."""
    sid, rid, uid, oid = uuid4(), uuid4(), uuid4(), uuid4()
    plan = {
        "rounds": [{
            "name": "Recruiter Screen", "category": "screening",
            "duration_minutes": 30, "skills": [], "guidelines": [],
            "feedback_questions": [{"heading": "Motivation", "description": "Why us?"}],
            "screening": {"enabled": True, "questions": [{"title": "Q", "prompt": "P"}]},
        }],
    }
    mock_supabase.execute_async.side_effect = [
        MagicMock(data={"id": str(sid), "status": "submitted", "requisition_id": str(rid), "interview_plan": plan}),
        MagicMock(data=[]),
        MagicMock(data={"id": "new-round-1"}),
        MagicMock(data={"id": "fq-1"}),
        MagicMock(data={"id": str(rid)}),
        MagicMock(data={"id": str(sid)}),
    ]
    mock_supabase.rpc = AsyncMock(side_effect=RuntimeError("rpc boom"))

    svc = IntakePublishService(supabase_client=mock_supabase)
    # Must NOT raise — publish is resilient to a screening-materialization failure.
    result = await svc.publish(session_id=sid, user_id=uid, organization_id=oid)
    assert result["requisition_id"] == str(rid)


@pytest.mark.asyncio
async def test_publish_ats_round_seeds_map_and_promotes(mock_supabase):
    """A plan round tagged with an Ashby stage id seeds ats_stage_round_map for
    that round AND triggers ats_promote_interviews after the plan is written."""
    sid, rid, uid, oid = uuid4(), uuid4(), uuid4(), uuid4()
    plan = {
        "version": "v1", "round_count": 1,
        "rounds": [{
            "name": "Tech", "category": "coding", "duration_minutes": 60,
            "skills": ["Python"], "round_number": 1,
            "guidelines": [{"title": "x", "description": "y"}],
            "ats_stage_id": "st_tech", "ats_stage_name": "Tech",
            "feedback_questions": [
                {"heading": "Code Quality", "description": "Read."},
                {"heading": "Problem Solving", "description": "Decompose."},
            ],
        }],
    }
    mock_supabase.execute_async.side_effect = [
        MagicMock(data={"id": str(sid), "status": "submitted", "requisition_id": str(rid), "interview_plan": plan}),
        MagicMock(data=[]),                       # delete existing rounds
        MagicMock(data={"id": "new-round-1"}),    # insert round
        MagicMock(data={"id": "fq-1"}),           # feedback_question 1
        MagicMock(data={"id": "fq-2"}),           # feedback_question 2
        MagicMock(data=[]),                       # requisitions update -> planned
        MagicMock(data=[]),                       # intake_sessions update -> published
    ]
    svc = IntakePublishService(mock_supabase)
    with patch("app.api.v2.core.rpc.call_rpc", new=AsyncMock(return_value=[])) as crpc:
        await svc.publish(sid, uid, oid, edited_plan=plan)

    names = [c.args[1] for c in crpc.await_args_list]
    assert "ats_upsert_stage_round_map" in names      # map seeded for the ATS round
    assert "ats_promote_interviews" in names          # promotion fired

    seed = next(c for c in crpc.await_args_list if c.args[1] == "ats_upsert_stage_round_map")
    assert seed.args[2] == {
        "p_org_id": str(oid),
        "p_requisition_id": str(rid),
        "p_round_id": "new-round-1",
        "p_ats_stage_id": "st_tech",
        "p_ats_stage_name": "Tech",
    }
    promote = next(c for c in crpc.await_args_list if c.args[1] == "ats_promote_interviews")
    assert promote.args[2] == {"p_requisition_id": str(rid), "p_org": str(oid)}


@pytest.mark.asyncio
async def test_publish_non_ats_round_still_promotes_but_no_map(mock_supabase):
    """A round with NO ats_stage_id seeds no map but promotion still fires
    (the RPC no-ops for non-ATS reqs)."""
    sid, rid, uid, oid = uuid4(), uuid4(), uuid4(), uuid4()
    plan = {
        "version": "v1", "round_count": 1,
        "rounds": [{
            "name": "Tech", "category": "coding", "duration_minutes": 60,
            "skills": [], "round_number": 1, "guidelines": [],
            "feedback_questions": [{"heading": "Q", "description": "d"}],
        }],  # NO ats_stage_id
    }
    mock_supabase.execute_async.side_effect = [
        MagicMock(data={"id": str(sid), "status": "submitted", "requisition_id": str(rid), "interview_plan": plan}),
        MagicMock(data=[]),
        MagicMock(data={"id": "new-round-1"}),
        MagicMock(data={"id": "fq-1"}),
        MagicMock(data=[]),
        MagicMock(data=[]),
    ]
    svc = IntakePublishService(mock_supabase)
    with patch("app.api.v2.core.rpc.call_rpc", new=AsyncMock(return_value=[])) as crpc:
        await svc.publish(sid, uid, oid, edited_plan=plan)
    names = [c.args[1] for c in crpc.await_args_list]
    assert "ats_upsert_stage_round_map" not in names   # no stage id -> no map
    assert "ats_promote_interviews" in names           # promote still called


@pytest.mark.asyncio
async def test_publish_promote_failure_does_not_break_publish(mock_supabase):
    """An ATS RPC failure (seed or promote) must not break a successful publish."""
    sid, rid, uid, oid = uuid4(), uuid4(), uuid4(), uuid4()
    plan = {
        "version": "v1", "round_count": 1,
        "rounds": [{
            "name": "Tech", "category": "coding", "duration_minutes": 60,
            "skills": [], "round_number": 1, "guidelines": [],
            "ats_stage_id": "st_tech", "ats_stage_name": "Tech",
            "feedback_questions": [{"heading": "Q", "description": "d"}],
        }],
    }
    mock_supabase.execute_async.side_effect = [
        MagicMock(data={"id": str(sid), "status": "submitted", "requisition_id": str(rid), "interview_plan": plan}),
        MagicMock(data=[]),
        MagicMock(data={"id": "new-round-1"}),
        MagicMock(data={"id": "fq-1"}),
        MagicMock(data=[]),
        MagicMock(data=[]),
    ]
    svc = IntakePublishService(mock_supabase)
    with patch("app.api.v2.core.rpc.call_rpc", new=AsyncMock(side_effect=RuntimeError("ats down"))):
        result = await svc.publish(sid, uid, oid, edited_plan=plan)  # must NOT raise
    assert result["requisition_id"] == str(rid)


@pytest.mark.asyncio
async def test_publish_accepts_edited_plan_override(mock_supabase):
    sid, rid = uuid4(), uuid4()
    db_plan = {"rounds": [{"name": "old", "category": "coding", "skills": ["x"],
                           "duration_minutes": 30, "round_number": 1,
                           "guidelines": [], "feedback_questions": [{"heading": "x", "description": "y"}]}]}
    user_edited = {"rounds": [{"name": "Edited Coding", "category": "coding", "skills": ["Python"],
                               "duration_minutes": 60, "round_number": 1,
                               "guidelines": [{"title": "be specific", "description": "z"}],
                               "feedback_questions": [{"heading": "Code Quality", "description": "x"}]}]}
    mock_supabase.execute_async.side_effect = [
        MagicMock(data={"id": str(sid), "status": "submitted", "requisition_id": str(rid), "interview_plan": db_plan}),
        MagicMock(data=[]),
        MagicMock(data={"id": "new-round-1"}),
        MagicMock(data={"id": "fq-1"}),
        MagicMock(data={"id": str(rid)}),
        MagicMock(data={"id": str(sid)}),
    ]
    svc = IntakePublishService(supabase_client=mock_supabase)
    result = await svc.publish(session_id=sid, user_id=uuid4(), organization_id=uuid4(), edited_plan=user_edited)
    assert result["requisition_id"] == str(rid)
    insert_calls = [c for c in mock_supabase.insert.call_args_list]
    round_insert = next(c for c in insert_calls if "name" in (c.args[0] if c.args else {}))
    assert round_insert.args[0]["name"] == "Edited Coding"
