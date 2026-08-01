"""Unit tests for the shared intake _session_ops helpers (BE-A2)."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.intake._session_ops import (
    invoke_worker_or_rollback,
    load_owned_session,
    optimistic_flip,
)


@pytest.fixture
def supabase():
    c = MagicMock()
    for m in ("table", "select", "update", "eq", "in_", "single"):
        getattr(c, m).return_value = c
    c.execute_async = AsyncMock()
    return c


@pytest.mark.asyncio
async def test_load_owned_session_returns_row(supabase):
    sid = uuid4()
    supabase.execute_async.return_value = MagicMock(data={"id": str(sid), "status": "ready"})
    row = await load_owned_session(
        supabase, session_id=sid, user_id=uuid4(), organization_id=uuid4(), columns="id,status",
    )
    assert row == {"id": str(sid), "status": "ready"}


@pytest.mark.asyncio
async def test_load_owned_session_returns_none_when_missing(supabase):
    supabase.execute_async.return_value = MagicMock(data=None)
    row = await load_owned_session(
        supabase, session_id=uuid4(), user_id=uuid4(), organization_id=uuid4(), columns="id",
    )
    assert row is None


@pytest.mark.asyncio
async def test_optimistic_flip_true_when_row_matches(supabase):
    supabase.execute_async.return_value = MagicMock(data=[{"id": "abc"}])
    won = await optimistic_flip(
        supabase, session_id=uuid4(), user_id=uuid4(), organization_id=uuid4(),
        values={"status": "submitted"}, guards=[("in_", "status", ["ready", "active"])],
    )
    assert won is True


@pytest.mark.asyncio
async def test_optimistic_flip_false_when_no_row_matches(supabase):
    """No row matched the guard predicate (concurrent writer won the race) -> False,
    which the caller maps to a 409."""
    supabase.execute_async.return_value = MagicMock(data=[])
    won = await optimistic_flip(
        supabase, session_id=uuid4(), user_id=uuid4(), organization_id=uuid4(),
        values={"status": "submitted"}, guards=[("eq", "process_status", "idle")],
    )
    assert won is False


@pytest.mark.asyncio
async def test_optimistic_flip_applies_guard_predicate(supabase):
    await optimistic_flip(
        supabase, session_id=uuid4(), user_id=uuid4(), organization_id=uuid4(),
        values={"status": "submitted"}, guards=[("in_", "status", ["ready", "active"])],
    )
    in_calls = [c.args for c in supabase.in_.call_args_list]
    assert ("status", ["ready", "active"]) in in_calls


def _invoker(side_effect=None):
    """get_invoker() is sync and returns an object whose .invoke is async."""
    invoker = MagicMock()
    invoker.invoke = AsyncMock(side_effect=side_effect)
    return MagicMock(return_value=invoker)


@pytest.mark.asyncio
async def test_invoke_worker_or_rollback_rolls_back_and_reraises(supabase):
    """On dispatch failure the rollback UPDATE fires and the original error
    propagates (the caller maps it to 500)."""
    with patch("app.services.intake._session_ops.get_invoker",
               new=_invoker(RuntimeError("worker down"))):
        with pytest.raises(RuntimeError, match="worker down"):
            await invoke_worker_or_rollback(
                supabase, session_id=uuid4(), user_id=uuid4(), organization_id=uuid4(),
                target="context_builder", payload={"session_id": "x"},
                rollback_values={"status": "ready", "process_status": "failed"},
            )
    rollback_payload = supabase.update.call_args.args[0]
    assert rollback_payload["process_status"] == "failed"


@pytest.mark.asyncio
async def test_invoke_worker_or_rollback_no_rollback_on_success(supabase):
    with patch("app.services.intake._session_ops.get_invoker", new=_invoker()):
        await invoke_worker_or_rollback(
            supabase, session_id=uuid4(), user_id=uuid4(), organization_id=uuid4(),
            target="context_builder", payload={"session_id": "x"},
            rollback_values={"status": "ready"},
        )
    supabase.update.assert_not_called()
