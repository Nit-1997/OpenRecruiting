"""Publish hook → Phase C action handler.

These tests drive the REAL IntakePublishService.publish() (the heavy DB dance
is already covered by test_intake_publish_service.py) and assert ONLY the
Phase C wiring: the list returned by ats_promote_interviews reaches
act_on_promoted_interviews, and a handler failure never breaks publish.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.intake_publish_service import IntakePublishService


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


def _minimal_plan():
    # No ats_stage_id -> only ats_promote_interviews flows through call_rpc.
    return {
        "version": "v1",
        "round_count": 1,
        "rounds": [
            {
                "name": "Tech",
                "category": "coding",
                "duration_minutes": 60,
                "skills": [],
                "round_number": 1,
                "guidelines": [],
                "feedback_questions": [{"heading": "Q", "description": "d"}],
            }
        ],
    }


def _publish_side_effect(sid, rid, plan):
    return [
        MagicMock(
            data={
                "id": str(sid),
                "status": "submitted",
                "requisition_id": str(rid),
                "interview_plan": plan,
            }
        ),
        MagicMock(data=[]),  # delete existing rounds
        MagicMock(data={"id": "new-round-1"}),  # insert round
        MagicMock(data={"id": "fq-1"}),  # feedback_question 1
        MagicMock(data=[]),  # requisitions update -> planned
        MagicMock(data=[]),  # intake_sessions update -> published
    ]


_PROMOTED = [
    {
        "candidate_round_id": "cr-1",
        "scheduled_start": "2099-01-01T00:00:00Z",
        "meeting_url": "https://zoom.us/j/1",
        "notetaker_transcript_id": None,
        "status": "scheduled",
        "ats_interview_event_id": "evt-1",
        "candidate_name": "Jordan Lee",
        "organization_id": "org-1",
    }
]


@pytest.mark.asyncio
async def test_publish_invokes_interview_actions(mock_supabase):
    sid, rid, uid, oid = uuid4(), uuid4(), uuid4(), uuid4()
    plan = _minimal_plan()
    mock_supabase.execute_async.side_effect = _publish_side_effect(sid, rid, plan)

    captured = {}

    async def _fake_act(supabase, promoted, *, bundle=None):
        captured["promoted"] = promoted

    svc = IntakePublishService(mock_supabase)
    with patch(
        "app.api.v2.core.rpc.call_rpc", new=AsyncMock(return_value=_PROMOTED)
    ), patch(
        "app.services.intake_publish_service.act_on_promoted_interviews",
        new=_fake_act,
    ):
        await svc.publish(sid, uid, oid, edited_plan=plan)

    assert captured["promoted"] == _PROMOTED


@pytest.mark.asyncio
async def test_publish_succeeds_when_interview_actions_raises(mock_supabase):
    """A Phase C handler failure must NOT break a successful publish."""
    sid, rid, uid, oid = uuid4(), uuid4(), uuid4(), uuid4()
    plan = _minimal_plan()
    mock_supabase.execute_async.side_effect = _publish_side_effect(sid, rid, plan)

    async def _boom(supabase, promoted, *, bundle=None):
        raise RuntimeError("recall/transcript explosion")

    svc = IntakePublishService(mock_supabase)
    with patch(
        "app.api.v2.core.rpc.call_rpc", new=AsyncMock(return_value=_PROMOTED)
    ), patch(
        "app.services.intake_publish_service.act_on_promoted_interviews",
        new=_boom,
    ):
        result = await svc.publish(sid, uid, oid, edited_plan=plan)

    # publish still returns success despite the handler raising
    assert result["requisition_id"] == str(rid)
