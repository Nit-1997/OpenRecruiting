"""Tests for session persistence helpers — uses mocked Supabase client."""

from unittest.mock import MagicMock, AsyncMock, call
import pytest
from intake_core.persistence import (
    load_session,
    append_turn,
    update_current_answers,
    update_process_stage,
    aload_session,
    aappend_turn,
    aupdate_current_answers,
    aupdate_process_stage,
)


# ---------------------------------------------------------------------------
# Sync fixtures (Lambda / supabase-py path)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_client():
    client = MagicMock()
    client.table.return_value = client
    client.select.return_value = client
    client.eq.return_value = client
    client.single.return_value = client
    client.update.return_value = client
    client.execute = MagicMock(return_value=MagicMock(data={"id": "abc"}))
    # rpc() returns a builder whose .execute() must be called
    rpc_builder = MagicMock()
    rpc_builder.execute = MagicMock(return_value=MagicMock(data=None))
    client.rpc = MagicMock(return_value=rpc_builder)
    return client


def test_load_session_returns_row(mock_client):
    mock_client.execute.return_value = MagicMock(data={
        "id": "abc", "form_data": {"role_name": "x"}, "turns": [], "current_answers": {}
    })
    row = load_session(mock_client, "abc")
    assert row["id"] == "abc"
    mock_client.table.assert_called_with("intake_sessions")


def test_append_turn_writes_jsonb_array(mock_client):
    turn = {"role": "user", "content": "hi", "modality": "voice", "idx": 0}
    append_turn(mock_client, "abc", turn)
    mock_client.rpc.assert_called_once()
    args = mock_client.rpc.call_args
    assert args[0][0] == "intake_sessions_append_turn"
    assert args[0][1]["p_session_id"] == "abc"
    # Must call .execute() on the builder
    mock_client.rpc.return_value.execute.assert_called_once()


def test_update_current_answers_merges_patch(mock_client):
    patch = {"q4_must_haves": {"status": "discussed", "text": "Python"}}
    update_current_answers(mock_client, "abc", patch)
    mock_client.rpc.assert_called_once_with(
        "intake_sessions_merge_answers",
        {"p_session_id": "abc", "p_patch": patch},
    )
    mock_client.rpc.return_value.execute.assert_called_once()


def test_update_process_stage_appends(mock_client):
    update_process_stage(mock_client, "abc", stage_name="parse_jd", status="running")
    mock_client.rpc.assert_called_once()
    args = mock_client.rpc.call_args
    assert args[0][0] == "intake_sessions_set_stage"
    mock_client.rpc.return_value.execute.assert_called_once()


# ---------------------------------------------------------------------------
# Async fixtures (FastAPI / SupabaseAdminClient path)
# ---------------------------------------------------------------------------

@pytest.fixture
def async_mock_client():
    """Simulates SupabaseAdminClient: rpc() is a coroutine, table ops use execute_async()."""
    client = MagicMock()
    # table(...).select(...).eq(...).single().execute_async() chain
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.single.return_value = chain
    chain.execute_async = AsyncMock(return_value=MagicMock(data={"id": "abc", "turns": []}))
    client.table.return_value = chain
    # rpc() is async, returns TableResponse directly
    client.rpc = AsyncMock(return_value=MagicMock(data=None))
    return client, chain


@pytest.mark.asyncio
async def test_aload_session_returns_row(async_mock_client):
    client, chain = async_mock_client
    chain.execute_async.return_value = MagicMock(data={
        "id": "abc", "form_data": {"role_name": "x"}, "turns": [], "current_answers": {}
    })
    row = await aload_session(client, "abc")
    assert row["id"] == "abc"
    client.table.assert_called_with("intake_sessions")
    chain.execute_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_aappend_turn_calls_rpc(async_mock_client):
    client, _ = async_mock_client
    turn = {"role": "user", "content": "hi", "modality": "text", "idx": 0}
    await aappend_turn(client, "abc", turn)
    client.rpc.assert_awaited_once_with(
        "intake_sessions_append_turn",
        {"p_session_id": "abc", "p_turn": turn},
    )


@pytest.mark.asyncio
async def test_aupdate_current_answers_calls_rpc(async_mock_client):
    client, _ = async_mock_client
    patch = {"q4_must_haves": {"status": "discussed", "text": "Python"}}
    await aupdate_current_answers(client, "abc", patch)
    client.rpc.assert_awaited_once_with(
        "intake_sessions_merge_answers",
        {"p_session_id": "abc", "p_patch": patch},
    )


@pytest.mark.asyncio
async def test_aupdate_process_stage_calls_rpc(async_mock_client):
    client, _ = async_mock_client
    await aupdate_process_stage(client, "abc", stage_name="parse_jd", status="running")
    client.rpc.assert_awaited_once()
    call_args = client.rpc.call_args
    assert call_args[0][0] == "intake_sessions_set_stage"
    assert call_args[0][1]["p_session_id"] == "abc"
    assert call_args[0][1]["p_stage_name"] == "parse_jd"
    assert call_args[0][1]["p_status"] == "running"


# ---------------------------------------------------------------------------
# 204 No Content smoke tests — async helpers must not raise when rpc() returns
# data=None (the behaviour after the wrapper fix for RETURNS VOID RPCs).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aappend_turn_tolerates_204_response(async_mock_client):
    """aappend_turn must succeed when the wrapper returns data=None (204 path)."""
    client, _ = async_mock_client
    client.rpc = AsyncMock(return_value=MagicMock(data=None))
    turn = {"role": "user", "content": "hello", "modality": "text", "idx": 0}
    await aappend_turn(client, "s1", turn)
    client.rpc.assert_awaited_once_with(
        "intake_sessions_append_turn",
        {"p_session_id": "s1", "p_turn": turn},
    )


@pytest.mark.asyncio
async def test_aupdate_current_answers_tolerates_204_response(async_mock_client):
    """aupdate_current_answers must succeed when the wrapper returns data=None (204 path)."""
    client, _ = async_mock_client
    client.rpc = AsyncMock(return_value=MagicMock(data=None))
    patch = {"q1": {"status": "discussed", "text": "Python"}}
    await aupdate_current_answers(client, "s1", patch)
    client.rpc.assert_awaited_once_with(
        "intake_sessions_merge_answers",
        {"p_session_id": "s1", "p_patch": patch},
    )


@pytest.mark.asyncio
async def test_aupdate_process_stage_tolerates_204_response(async_mock_client):
    """aupdate_process_stage must succeed when the wrapper returns data=None (204 path)."""
    client, _ = async_mock_client
    client.rpc = AsyncMock(return_value=MagicMock(data=None))
    await aupdate_process_stage(client, "s1", stage_name="parse_jd", status="done")
    client.rpc.assert_awaited_once()
    call_args = client.rpc.call_args
    assert call_args[0][0] == "intake_sessions_set_stage"
