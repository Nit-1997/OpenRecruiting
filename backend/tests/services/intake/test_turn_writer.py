"""Tests for the turn_writer helper used by the text path."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.intake.turn_writer import append_turn_for_session


@pytest.fixture
def mock_supabase():
    client = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.single.return_value = chain
    chain.execute_async = AsyncMock(return_value=MagicMock(data={"turns": []}))
    client.table.return_value = chain
    client.rpc = AsyncMock(return_value=MagicMock(data=None))
    return client, chain


@pytest.mark.asyncio
async def test_append_turn_assigns_next_idx_when_empty(mock_supabase):
    client, chain = mock_supabase
    chain.execute_async.return_value = MagicMock(data={"turns": []})
    with patch("app.services.intake.turn_writer.aappend_turn", new=AsyncMock()) as mock_append:
        turn = await append_turn_for_session(
            client, session_id="sess-1",
            role="user", content="hello", modality="text",
        )
    assert turn["idx"] == 0
    assert turn["role"] == "user"
    assert turn["content"] == "hello"
    assert turn["modality"] == "text"
    assert "timestamp" in turn
    mock_append.assert_awaited_once_with(client, "sess-1", turn)


@pytest.mark.asyncio
async def test_append_turn_assigns_next_idx_when_three_existing(mock_supabase):
    client, chain = mock_supabase
    chain.execute_async.return_value = MagicMock(data={"turns": [
        {"idx": 0}, {"idx": 1}, {"idx": 2},
    ]})
    with patch("app.services.intake.turn_writer.aappend_turn", new=AsyncMock()) as mock_append:
        turn = await append_turn_for_session(
            client, session_id="sess-1",
            role="assistant", content="hi", modality="text",
        )
    assert turn["idx"] == 3
    mock_append.assert_awaited_once()


@pytest.mark.asyncio
async def test_append_turn_carries_tool_calls(mock_supabase):
    client, chain = mock_supabase
    chain.execute_async.return_value = MagicMock(data={"turns": []})
    with patch("app.services.intake.turn_writer.aappend_turn", new=AsyncMock()):
        turn = await append_turn_for_session(
            client, session_id="sess-1",
            role="assistant", content="ok",
            modality="text",
            tool_calls=[{"name": "update_answer", "args": {"qid": "q4_must_haves"}}],
        )
    assert turn["tool_calls"][0]["name"] == "update_answer"


@pytest.mark.asyncio
async def test_append_turn_handles_missing_turns_field(mock_supabase):
    client, chain = mock_supabase
    chain.execute_async.return_value = MagicMock(data={})  # no 'turns' key
    with patch("app.services.intake.turn_writer.aappend_turn", new=AsyncMock()):
        turn = await append_turn_for_session(
            client, session_id="sess-1",
            role="user", content="x", modality="text",
        )
    assert turn["idx"] == 0
