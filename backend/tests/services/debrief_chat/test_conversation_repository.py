"""Unit tests for DebriefConversationRepository — the turn store for debrief chat.

The DB boundary is a fluent MagicMock (mirrors test_debrief_repository.py). Every
method goes through execute_async / rpc — never sync .execute(). A packet with no
conversation row reads as [], not an error (single() -> None contract).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.debrief_chat.conversation_repository import (
    DebriefConversationRepository,
)

PACKET_ID = "00000000-0000-0000-0000-0000000000f1"


def _supa(*, select_data=None, rpc_data=None):
    """A fluent Supabase builder: table().select().eq().single().execute_async()
    yields `select_data`; rpc(...) yields `rpc_data`."""
    builder = MagicMock()
    for m in ("table", "select", "eq", "single"):
        getattr(builder, m).return_value = builder
    builder.execute_async = AsyncMock(return_value=MagicMock(data=select_data))
    supa = MagicMock()
    supa.table.return_value = builder
    supa.rpc = AsyncMock(return_value=MagicMock(data=rpc_data))
    return supa, builder


@pytest.mark.asyncio
async def test_load_turns_empty_when_no_row():
    """No conversation row yet -> single() returns None -> [] (not an error)."""
    supa, _ = _supa(select_data=None)
    repo = DebriefConversationRepository(supa)
    out = await repo.load_turns(PACKET_ID)
    assert out == []


@pytest.mark.asyncio
async def test_load_turns_returns_stored_turns():
    turns = [{"role": "user", "text": "why A?", "idx": 0}]
    supa, builder = _supa(select_data={"turns": turns})
    repo = DebriefConversationRepository(supa)
    out = await repo.load_turns(PACKET_ID)
    assert out == turns
    builder.eq.assert_called_with("packet_id", PACKET_ID)


@pytest.mark.asyncio
async def test_load_turns_empty_when_turns_null():
    """A row exists but turns is null -> [] (defensive coalesce)."""
    supa, _ = _supa(select_data={"turns": None})
    repo = DebriefConversationRepository(supa)
    out = await repo.load_turns(PACKET_ID)
    assert out == []


@pytest.mark.asyncio
async def test_append_turn_calls_rpc_and_returns_turn_with_idx():
    turn = {"role": "user", "text": "why A?"}
    returned = {"role": "user", "text": "why A?", "idx": 0}
    supa, _ = _supa(rpc_data=returned)
    repo = DebriefConversationRepository(supa)
    out = await repo.append_turn(PACKET_ID, turn)
    assert out == returned
    supa.rpc.assert_awaited_once()
    name, params = supa.rpc.call_args.args
    assert name == "debrief_conversation_append_turn"
    assert params["p_packet_id"] == PACKET_ID
    # The repo stamps a server-side UTC `ts` on every turn it appends.
    sent = params["p_turn"]
    assert sent["role"] == turn["role"]
    assert sent["text"] == turn["text"]
    assert isinstance(sent.get("ts"), str) and sent["ts"]
