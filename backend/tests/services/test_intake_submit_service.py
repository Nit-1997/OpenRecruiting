"""Tests for IntakeSubmitService."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.intake_submit_service import IntakeSubmitService, IntakeSubmitError


@pytest.fixture
def mock_supabase():
    client = MagicMock()
    client.table.return_value = client
    client.select.return_value = client
    client.eq.return_value = client
    client.in_.return_value = client
    client.single.return_value = client
    client.update.return_value = client
    client.execute_async = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_submit_invokes_lambda_when_session_ready(mock_supabase):
    sid = uuid4()
    uid = uuid4()
    oid = uuid4()
    rid = uuid4()
    mock_supabase.execute_async.side_effect = [
        # 1st: select session (status='ready')
        MagicMock(data={"id": str(sid), "status": "ready", "current_answers": {"q1_role_overview": {"text": "x"}}, "requisition_id": str(rid)}),
        # 2nd: update session to 'submitted'
        MagicMock(data=[{"id": str(sid)}]),
        # 3rd: update requisition draft → intake_pending
        MagicMock(data=[{"id": str(rid)}]),
    ]
    mock_invoke = AsyncMock()
    with patch("app.services.intake._session_ops.get_invoker",
               new=MagicMock(return_value=MagicMock(invoke=mock_invoke))):
        svc = IntakeSubmitService(supabase_client=mock_supabase)
        result = await svc.submit(session_id=sid, user_id=uid, organization_id=oid)
    assert result["session_id"] == str(sid)
    assert result["status"] == "submitted"
    mock_invoke.assert_awaited_once()
    assert mock_invoke.await_args.args[1] == {"session_id": str(sid)}


@pytest.mark.asyncio
async def test_submit_invokes_lambda_when_session_active(mock_supabase):
    """A mid-conversation session (status='active') is submittable — the modal offers
    'submit at N/9, the rest are optional'. Regression for the ready-only gate that made
    every in-progress session permanently un-submittable."""
    sid = uuid4()
    uid = uuid4()
    oid = uuid4()
    rid = uuid4()
    mock_supabase.execute_async.side_effect = [
        MagicMock(data={"id": str(sid), "status": "active", "current_answers": {"q1_role_overview": {"text": "x"}}, "requisition_id": str(rid)}),
        MagicMock(data=[{"id": str(sid)}]),
        MagicMock(data=[{"id": str(rid)}]),
    ]
    mock_invoke = AsyncMock()
    with patch("app.services.intake._session_ops.get_invoker",
               new=MagicMock(return_value=MagicMock(invoke=mock_invoke))):
        svc = IntakeSubmitService(supabase_client=mock_supabase)
        result = await svc.submit(session_id=sid, user_id=uid, organization_id=oid)
    assert result["status"] == "submitted"
    mock_invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_rejects_prefilling_session(mock_supabase):
    """A session still prefilling has no usable answers yet — not submittable (409)."""
    sid = uuid4()
    mock_supabase.execute_async.return_value = MagicMock(data={
        "id": str(sid), "status": "prefilling", "current_answers": {"q1": {"text": "x"}}, "requisition_id": None,
    })
    svc = IntakeSubmitService(supabase_client=mock_supabase)
    with pytest.raises(IntakeSubmitError) as exc:
        await svc.submit(session_id=sid, user_id=uuid4(), organization_id=uuid4())
    assert exc.value.status_code == 409
    assert "still prefilling" in exc.value.message


@pytest.mark.asyncio
async def test_submit_rejects_published_session(mock_supabase):
    sid = uuid4()
    mock_supabase.execute_async.return_value = MagicMock(data={
        "id": str(sid), "status": "published", "current_answers": {}
    })
    svc = IntakeSubmitService(supabase_client=mock_supabase)
    with pytest.raises(IntakeSubmitError, match="already published"):
        await svc.submit(session_id=sid, user_id=uuid4(), organization_id=uuid4())


@pytest.mark.asyncio
async def test_submit_rejects_missing_answers(mock_supabase):
    sid = uuid4()
    mock_supabase.execute_async.return_value = MagicMock(data={
        "id": str(sid), "status": "ready", "current_answers": None
    })
    svc = IntakeSubmitService(supabase_client=mock_supabase)
    with pytest.raises(IntakeSubmitError, match="no current_answers"):
        await svc.submit(session_id=sid, user_id=uuid4(), organization_id=uuid4())


@pytest.mark.asyncio
async def test_submit_returns_409_when_already_submitting(mock_supabase):
    sid = uuid4()
    mock_supabase.execute_async.return_value = MagicMock(data={
        "id": str(sid), "status": "submitted", "current_answers": {"q1_role_overview": {"text": "x"}}
    })
    svc = IntakeSubmitService(supabase_client=mock_supabase)
    with pytest.raises(IntakeSubmitError, match="already submitted"):
        await svc.submit(session_id=sid, user_id=uuid4(), organization_id=uuid4())


@pytest.mark.asyncio
async def test_submit_cross_tenant_returns_404(mock_supabase):
    """When WHERE user_id+org_id filters match nothing, submit raises 404 IntakeSubmitError."""
    sid = uuid4()
    mock_supabase.execute_async.return_value = MagicMock(data=None)
    svc = IntakeSubmitService(supabase_client=mock_supabase)
    with pytest.raises(IntakeSubmitError) as exc:
        await svc.submit(session_id=sid, user_id=uuid4(), organization_id=uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_submit_advances_requisition_to_intake_pending(mock_supabase):
    """submit() must call requisitions.update with status=intake_pending after session flip."""
    sid = uuid4()
    uid = uuid4()
    oid = uuid4()
    rid = uuid4()
    mock_supabase.execute_async.side_effect = [
        MagicMock(data={"id": str(sid), "status": "ready", "current_answers": {"q1": {"text": "x"}}, "requisition_id": str(rid)}),
        MagicMock(data=[{"id": str(sid)}]),
        MagicMock(data=[{"id": str(rid)}]),
    ]
    with patch("app.services.intake._session_ops.get_invoker",
               new=MagicMock(return_value=MagicMock(invoke=AsyncMock()))):
        svc = IntakeSubmitService(supabase_client=mock_supabase)
        await svc.submit(session_id=sid, user_id=uid, organization_id=oid)

    # Verify the update call that advances the requisition included the status=intake_pending payload
    update_calls = [c for c in mock_supabase.update.call_args_list if c.args and c.args[0].get("status") == "intake_pending"]
    assert len(update_calls) == 1, "Expected exactly one requisitions.update({'status': 'intake_pending'}) call"


@pytest.mark.asyncio
async def test_submit_requisition_update_scoped_to_organization(mock_supabase):
    """The requisition status update must be scoped to organization_id, not org-unscoped."""
    sid = uuid4()
    uid = uuid4()
    oid = uuid4()
    rid = uuid4()
    mock_supabase.execute_async.side_effect = [
        MagicMock(data={"id": str(sid), "status": "ready", "current_answers": {"q1": {"text": "x"}}, "requisition_id": str(rid)}),
        MagicMock(data=[{"id": str(sid)}]),
        MagicMock(data=[{"id": str(rid)}]),
    ]
    with patch("app.services.intake._session_ops.get_invoker",
               new=MagicMock(return_value=MagicMock(invoke=AsyncMock()))):
        svc = IntakeSubmitService(supabase_client=mock_supabase)
        await svc.submit(session_id=sid, user_id=uid, organization_id=oid)

    # The eq() chain on the mock records every call; verify organization_id was passed
    eq_calls = [c.args for c in mock_supabase.eq.call_args_list]
    assert ("organization_id", str(oid)) in eq_calls, "requisition update must be scoped by organization_id"


@pytest.mark.asyncio
async def test_submit_returns_409_when_atomic_update_matches_no_row(mock_supabase):
    """When the status IN ('ready','active') predicate in the UPDATE matches nothing (row was
    already transitioned by a concurrent request), submit() raises IntakeSubmitError with 409."""
    sid = uuid4()
    uid = uuid4()
    oid = uuid4()
    mock_supabase.execute_async.side_effect = [
        # select: session exists and looks ready
        MagicMock(data={"id": str(sid), "status": "ready", "current_answers": {"q1": {"text": "x"}}, "requisition_id": None}),
        # update: zero rows matched — concurrent request already flipped status
        MagicMock(data=[]),
    ]
    svc = IntakeSubmitService(supabase_client=mock_supabase)
    with pytest.raises(IntakeSubmitError) as exc:
        await svc.submit(session_id=sid, user_id=uid, organization_id=oid)
    assert exc.value.status_code == 409
    assert "submittable state" in exc.value.message


@pytest.mark.asyncio
async def test_submit_atomic_predicate_included_in_update(mock_supabase):
    """The UPDATE query must include .in_('status', ['ready','active']) so Postgres enforces
    the transition atomically and prevents double Lambda invocation."""
    sid = uuid4()
    uid = uuid4()
    oid = uuid4()
    rid = uuid4()
    mock_supabase.execute_async.side_effect = [
        MagicMock(data={"id": str(sid), "status": "active", "current_answers": {"q1": {"text": "x"}}, "requisition_id": str(rid)}),
        MagicMock(data=[{"id": str(sid)}]),
        MagicMock(data=[{"id": str(rid)}]),
    ]
    with patch("app.services.intake._session_ops.get_invoker",
               new=MagicMock(return_value=MagicMock(invoke=AsyncMock()))):
        svc = IntakeSubmitService(supabase_client=mock_supabase)
        await svc.submit(session_id=sid, user_id=uid, organization_id=oid)

    in_calls = [c.args for c in mock_supabase.in_.call_args_list]
    assert ("status", ["ready", "active"]) in in_calls, (
        "UPDATE must filter .in_('status', ['ready','active']) to act as an atomic transition gate"
    )


@pytest.mark.asyncio
async def test_submit_rolls_back_status_on_lambda_failure(mock_supabase):
    """When the Lambda invoke fails, submit() rolls the session status back (so the user can
    retry) and surfaces a 500 IntakeSubmitError. The rollback is the 4th execute_async call."""
    sid = uuid4()
    uid = uuid4()
    oid = uuid4()
    rid = uuid4()
    mock_supabase.execute_async.side_effect = [
        MagicMock(data={"id": str(sid), "status": "ready", "current_answers": {"q1": {"text": "x"}}, "requisition_id": str(rid)}),
        MagicMock(data=[{"id": str(sid)}]),    # optimistic flip won
        MagicMock(data=[{"id": str(rid)}]),    # requisition advance
        MagicMock(data=[{"id": str(sid)}]),    # rollback update
    ]
    with patch("app.services.intake._session_ops.get_invoker",
               new=MagicMock(return_value=MagicMock(
                   invoke=AsyncMock(side_effect=RuntimeError("worker down"))))):
        svc = IntakeSubmitService(supabase_client=mock_supabase)
        with pytest.raises(IntakeSubmitError) as exc:
            await svc.submit(session_id=sid, user_id=uid, organization_id=oid)
    assert exc.value.status_code == 500
    rollback_payload = mock_supabase.update.call_args.args[0]
    assert rollback_payload["process_status"] == "failed"


@pytest.mark.asyncio
async def test_submit_concurrent_second_request_does_not_invoke_lambda(mock_supabase):
    """Simulate two concurrent submits in the same process (warm-container style).
    First call succeeds; second call sees update return empty data (row already 'submitted')
    and must raise 409 WITHOUT invoking Lambda a second time."""
    sid = uuid4()
    uid = uuid4()
    oid = uuid4()

    invoke_count = 0

    async def fake_invoke(*args, **kwargs):
        nonlocal invoke_count
        invoke_count += 1

    # First request: select sees 'ready', update succeeds
    first_select = MagicMock(data={"id": str(sid), "status": "ready", "current_answers": {"q1": {"text": "x"}}, "requisition_id": None})
    first_update = MagicMock(data=[{"id": str(sid)}])
    # Second request: select still sees 'ready' (read happened before first update committed),
    # but update returns empty — first request won the row lock
    second_select = MagicMock(data={"id": str(sid), "status": "ready", "current_answers": {"q1": {"text": "x"}}, "requisition_id": None})
    second_update = MagicMock(data=[])

    with patch("app.services.intake._session_ops.get_invoker",
               new=MagicMock(return_value=MagicMock(invoke=AsyncMock(side_effect=fake_invoke)))):
        svc = IntakeSubmitService(supabase_client=mock_supabase)
        mock_supabase.execute_async.side_effect = [first_select, first_update]
        result = await svc.submit(session_id=sid, user_id=uid, organization_id=oid)
        assert result["status"] == "submitted"
        assert invoke_count == 1

        mock_supabase.execute_async.side_effect = [second_select, second_update]
        with pytest.raises(IntakeSubmitError) as exc:
            await svc.submit(session_id=sid, user_id=uid, organization_id=oid)
        assert exc.value.status_code == 409
        assert invoke_count == 1, "Lambda must NOT be invoked a second time"
