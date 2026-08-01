"""Tests for active_modality lock manipulation (deterministic RPC acquire)."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.modality_lock import (
    ModalityConflictError,
    require_no_other_modality,
    set_modality,
)


@pytest.fixture
def mock_supabase():
    client = MagicMock()
    client.table.return_value = client
    client.select.return_value = client
    client.update.return_value = client
    client.eq.return_value = client
    client.execute_async = AsyncMock()
    client.rpc = AsyncMock()
    return client


def _rpc(value):
    return MagicMock(data=value)


@pytest.mark.asyncio
async def test_require_no_other_modality_wins_when_rpc_true(mock_supabase):
    """RPC returns true (free lock or same modality) -> no error, no existence read."""
    mock_supabase.rpc.return_value = _rpc(True)
    await require_no_other_modality(mock_supabase, session_id=uuid4(), self_modality="voice")
    mock_supabase.rpc.assert_awaited_once()
    assert mock_supabase.rpc.call_args.args[0] == "set_active_modality"
    # Won outright — no disambiguating existence read.
    mock_supabase.execute_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_require_no_other_modality_raises_conflict_when_rpc_false_and_row_exists(mock_supabase):
    """RPC false + the session row exists -> the OTHER modality holds it -> 409."""
    mock_supabase.rpc.return_value = _rpc(False)
    mock_supabase.execute_async.return_value = MagicMock(data=[{"id": "abc"}])
    with pytest.raises(ModalityConflictError) as exc:
        await require_no_other_modality(mock_supabase, session_id=uuid4(), self_modality="voice")
    assert exc.value.requested == "voice"


@pytest.mark.asyncio
async def test_require_no_other_modality_raises_lookup_when_rpc_false_and_row_missing(mock_supabase):
    """RPC false + no such row for this caller -> 404 (not a conflict)."""
    mock_supabase.rpc.return_value = _rpc(False)
    mock_supabase.execute_async.return_value = MagicMock(data=[])
    with pytest.raises(LookupError):
        await require_no_other_modality(
            mock_supabase, session_id=uuid4(), self_modality="voice",
            organization_id=uuid4(), user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_require_no_other_modality_passes_user_id_to_rpc(mock_supabase):
    """The acquire RPC must be scoped by p_user_id (tenant scope)."""
    uid = uuid4()
    mock_supabase.rpc.return_value = _rpc(True)
    await require_no_other_modality(
        mock_supabase, session_id=uuid4(), self_modality="text", user_id=uid,
    )
    params = mock_supabase.rpc.call_args.args[1]
    assert params["p_user_id"] == str(uid)
    assert params["p_modality"] == "text"


@pytest.mark.asyncio
async def test_two_concurrent_acquires_first_wins_second_conflicts(mock_supabase):
    """Two voice-start acquires serialize on the warm row lock: RPC true then false.
    First wins (no error); second loses (-> ModalityConflictError -> 409)."""
    sid = uuid4()
    uid = uuid4()
    mock_supabase.rpc.side_effect = [_rpc(True), _rpc(False)]
    mock_supabase.execute_async.return_value = MagicMock(data=[{"id": "abc"}])

    # First caller wins.
    await require_no_other_modality(mock_supabase, session_id=sid, self_modality="voice", user_id=uid)

    # Second caller loses -> deterministic conflict.
    with pytest.raises(ModalityConflictError):
        await require_no_other_modality(mock_supabase, session_id=sid, self_modality="voice", user_id=uid)


@pytest.mark.asyncio
async def test_set_modality_force(mock_supabase):
    """set_modality is the unconditional setter — used by switch endpoint after drain."""
    await set_modality(mock_supabase, session_id=uuid4(), modality="text")
    assert mock_supabase.update.call_args.args[0]["active_modality"] == "text"


@pytest.mark.asyncio
async def test_set_modality_clear_releases_lock(mock_supabase):
    """modality=None clears the lock (release path)."""
    await set_modality(mock_supabase, session_id=uuid4(), modality=None)
    assert mock_supabase.update.call_args.args[0]["active_modality"] is None


@pytest.mark.asyncio
async def test_set_modality_with_scoping_passes_filters(mock_supabase):
    oid = uuid4()
    uid = uuid4()
    await set_modality(
        mock_supabase, session_id=uuid4(), modality="voice",
        organization_id=oid, user_id=uid,
    )
    eq_keys = [c.args[0] for c in mock_supabase.eq.call_args_list]
    assert "organization_id" in eq_keys
    assert "user_id" in eq_keys
