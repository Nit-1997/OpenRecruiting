"""Tests for IntakeSessionService.list_user_sessions (B1.1)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.intake_session_service import IntakeSessionService


@pytest.fixture
def mock_supabase():
    client = MagicMock()
    client.table.return_value = client
    client.select.return_value = client
    client.eq.return_value = client
    client.in_.return_value = client
    client.is_.return_value = client
    client.order.return_value = client
    client.limit.return_value = client
    client.execute_async = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_list_user_sessions_queries_view_with_user_filter(mock_supabase):
    user_id = uuid4()
    org_id = uuid4()
    sid = uuid4()
    rid = uuid4()
    view_rows = MagicMock(data=[
        {
            "conversation_id": str(sid),
            "user_id": str(user_id),
            "organization_id": str(org_id),
            "kind": "intake",
            "title": "Intake: Senior BE",
            "role_name": "Senior BE",
            "exp_min": 5,
            "exp_max": 8,
            "location": "Remote · US",
            "display_status": "incomplete",
            "detail_status": "created",
            "active_modality": None,
            "requisition_id": str(rid),
            "last_activity_at": datetime.now(timezone.utc).isoformat(),
            "resume_url": f"/intake/sessions/{sid}",
        },
    ])
    # Calls in order: view query, coverage (intake_sessions), rounds, candidates.
    mock_supabase.execute_async.side_effect = [
        view_rows,
        MagicMock(data=[]),  # coverage rows
        MagicMock(data=[]),  # rounds rows
        MagicMock(data=[]),  # candidate rows
    ]

    svc = IntakeSessionService(supabase_client=mock_supabase)
    result = await svc.list_user_sessions(user_id=user_id, organization_id=org_id)

    assert len(result.sessions) == 1
    item = result.sessions[0]
    assert str(item.session_id) == str(sid)
    assert item.title == "Intake: Senior BE"
    assert item.display_status == "incomplete"
    assert item.role_name == "Senior BE"
    assert item.exp_min == 5
    assert item.exp_max == 8
    assert item.location == "Remote · US"
    # Enriched fields default to empty coverage/plan stats when no rows.
    assert item.covered == 0
    assert item.total == 9
    assert item.rounds_count == 0
    assert item.candidates_count == 0

    mock_supabase.table.assert_any_call("user_conversation_history")
    mock_supabase.eq.assert_any_call("user_id", str(user_id))
    mock_supabase.order.assert_called_with("last_activity_at", desc=True)
    mock_supabase.limit.assert_called_with(50)


@pytest.mark.asyncio
async def test_list_user_sessions_returns_empty_when_none(mock_supabase):
    mock_supabase.execute_async.return_value = MagicMock(data=[])
    svc = IntakeSessionService(supabase_client=mock_supabase)
    result = await svc.list_user_sessions(user_id=uuid4(), organization_id=uuid4())
    assert result.sessions == []


@pytest.mark.asyncio
async def test_list_user_sessions_handles_null_data(mock_supabase):
    mock_supabase.execute_async.return_value = MagicMock(data=None)
    svc = IntakeSessionService(supabase_client=mock_supabase)
    result = await svc.list_user_sessions(user_id=uuid4(), organization_id=uuid4())
    assert result.sessions == []
