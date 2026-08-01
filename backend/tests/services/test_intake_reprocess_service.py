"""Tests for IntakeReprocessService — the 'process till now' orchestrator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.services.intake_reprocess_service import (
    IntakeReprocessError,
    IntakeReprocessService,
)


@pytest.fixture
def supabase():
    c = MagicMock()
    for m in ("table", "select", "update", "eq", "single"):
        getattr(c, m).return_value = c
    c.execute_async = AsyncMock()
    return c


@pytest.fixture
def session_id() -> UUID:
    return uuid4()


@pytest.fixture
def user_id() -> UUID:
    return uuid4()


@pytest.fixture
def org_id() -> UUID:
    return uuid4()


def _row(status="ready", process_status="idle", current_answers=None):
    return MagicMock(data={
        "id": "abc",
        "status": status,
        "process_status": process_status,
        "current_answers": current_answers or {"q1_role_overview": {"text": "x"}},
    })


@pytest.mark.asyncio
async def test_reprocess_404_when_session_not_found(supabase, session_id, user_id, org_id):
    supabase.execute_async.side_effect = [MagicMock(data=None)]
    svc = IntakeReprocessService(supabase_client=supabase)
    with pytest.raises(IntakeReprocessError) as exc:
        await svc.reprocess(session_id=session_id, user_id=user_id, organization_id=org_id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_reprocess_409_when_process_status_running(supabase, session_id, user_id, org_id):
    supabase.execute_async.side_effect = [_row(process_status="running")]
    svc = IntakeReprocessService(supabase_client=supabase)
    with pytest.raises(IntakeReprocessError) as exc:
        await svc.reprocess(session_id=session_id, user_id=user_id, organization_id=org_id)
    assert exc.value.status_code == 409
    assert "already running" in exc.value.message.lower()


@pytest.mark.asyncio
async def test_reprocess_happy_path_bumps_run_id_invokes_lambda(supabase, session_id, user_id, org_id):
    supabase.execute_async.side_effect = [
        _row(status="ready", process_status="idle"),
        MagicMock(data=[{"id": "abc", "process_status": "running"}]),
    ]
    mock_invoke = AsyncMock()
    with patch("app.services.intake._session_ops.get_invoker",
               new=MagicMock(return_value=MagicMock(invoke=mock_invoke))), \
         patch("app.services.intake_reprocess_service.uuid4", return_value=UUID("00000000-0000-0000-0000-000000000abc")):
        svc = IntakeReprocessService(supabase_client=supabase)
        result = await svc.reprocess(session_id=session_id, user_id=user_id, organization_id=org_id)

    assert result["session_id"] == str(session_id)
    assert result["process_run_id"] == "00000000-0000-0000-0000-000000000abc"
    mock_invoke.assert_awaited_once()
    payload = mock_invoke.await_args.args[1]
    assert payload == {"session_id": str(session_id), "include_turns": True}


@pytest.mark.asyncio
async def test_reprocess_update_payload_resets_process_stages_and_clears_error(supabase, session_id, user_id, org_id):
    supabase.execute_async.side_effect = [
        _row(),
        MagicMock(data=[{"id": "abc"}]),
    ]
    with patch("app.services.intake._session_ops.get_invoker",
               new=MagicMock(return_value=MagicMock(invoke=AsyncMock()))):
        svc = IntakeReprocessService(supabase_client=supabase)
        await svc.reprocess(session_id=session_id, user_id=user_id, organization_id=org_id)

    update_payload = supabase.update.call_args.args[0]
    assert update_payload["process_status"] == "running"
    assert update_payload["process_stages"] == []
    assert update_payload["process_error"] is None
    assert "process_run_id" in update_payload


@pytest.mark.asyncio
async def test_reprocess_atomic_race_loser_gets_409(supabase, session_id, user_id, org_id):
    supabase.execute_async.side_effect = [
        _row(),
        MagicMock(data=[]),
    ]
    with patch.dict("os.environ", {"INTAKE_CONTEXT_BUILDER_LAMBDA_ARN": "arn:1"}):
        svc = IntakeReprocessService(supabase_client=supabase)
        with pytest.raises(IntakeReprocessError) as exc:
            await svc.reprocess(session_id=session_id, user_id=user_id, organization_id=org_id)
        assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_reprocess_rolls_back_status_on_lambda_invoke_failure(supabase, session_id, user_id, org_id):
    supabase.execute_async.side_effect = [
        _row(),
        MagicMock(data=[{"id": "abc"}]),
        MagicMock(data=[{"id": "abc"}]),
    ]
    with patch("app.services.intake._session_ops.get_invoker",
               new=MagicMock(return_value=MagicMock(
                   invoke=AsyncMock(side_effect=RuntimeError("worker down"))))):
        svc = IntakeReprocessService(supabase_client=supabase)
        with pytest.raises(IntakeReprocessError) as exc:
            await svc.reprocess(session_id=session_id, user_id=user_id, organization_id=org_id)
        assert exc.value.status_code == 500
    rollback_payload = supabase.update.call_args.args[0]
    assert rollback_payload["process_status"] in ("idle", "failed")


@pytest.mark.asyncio
async def test_reprocess_unconfigured_target_returns_500(supabase, session_id, user_id, org_id):
    """With no worker configured for the target, dispatch raises and the caller
    still surfaces a 500 (the old behaviour was an explicit missing-ARN check;
    transport is now chosen by JOB_INVOKER, so an unroutable target is what
    signals 'not configured on this environment')."""
    from app.services.jobs.invoker import UnknownJobTargetError

    supabase.execute_async.side_effect = [
        _row(),
        MagicMock(data=[{"id": "abc"}]),
        MagicMock(data=[{"id": "abc"}]),
    ]
    with patch("app.services.intake._session_ops.get_invoker",
               new=MagicMock(return_value=MagicMock(
                   invoke=AsyncMock(side_effect=UnknownJobTargetError("no worker"))))):
        svc = IntakeReprocessService(supabase_client=supabase)
        with pytest.raises(IntakeReprocessError) as exc:
            await svc.reprocess(session_id=session_id, user_id=user_id, organization_id=org_id)
    assert exc.value.status_code == 500
