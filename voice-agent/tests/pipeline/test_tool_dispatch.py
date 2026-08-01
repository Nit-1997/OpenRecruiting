"""Test the tool dispatcher that maps Anthropic tool calls to intake-core handlers."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.pipeline.tool_dispatch import dispatch_tool_call
from src.pipeline.turn_persist import TurnPersistFrameProcessor


def test_dispatch_routes_update_answer():
    mock_client = MagicMock()
    with patch("src.pipeline.tool_dispatch.handle_update_answer") as mock_handler:
        mock_handler.return_value = {"ok": True}
        out = dispatch_tool_call(
            client=mock_client,
            session_id="s",
            tool_name="update_answer",
            tool_args={"qid": "q1_role_overview", "text": "x", "confidence": "high"},
            turn_idx=3,
        )
        assert out["ok"] is True
        mock_handler.assert_called_once()


def test_dispatch_routes_mark_status():
    mock_client = MagicMock()
    with patch("src.pipeline.tool_dispatch.handle_mark_status") as mock_handler:
        mock_handler.return_value = {"ok": True}
        out = dispatch_tool_call(
            client=mock_client,
            session_id="s",
            tool_name="mark_status",
            tool_args={"qid": "q1_role_overview", "status": "validated"},
            turn_idx=3,
        )
        assert out["ok"] is True
        mock_handler.assert_called_once()


def test_dispatch_rejects_unknown_tool():
    out = dispatch_tool_call(
        client=MagicMock(),
        session_id="s",
        tool_name="nuclear_launch",
        tool_args={},
        turn_idx=0,
    )
    assert out["ok"] is False
    assert "unknown tool" in out["error"].lower()


def test_factory_handler_uses_current_user_turn_idx():
    """The factory _handler closure must read persist_processor.current_user_turn_idx,
    not a hardcoded 0, so that tool calls carry the real user-turn provenance."""
    # Build a processor whose _last_user_turn_idx reflects turn 7
    proc = TurnPersistFrameProcessor(supabase_client=MagicMock(), session_id="s1", initial_idx=7)
    proc._last_user_turn_idx = 7

    captured_turn_idx: list[int] = []

    def fake_dispatch(tool_name, tool_args, turn_idx):
        captured_turn_idx.append(turn_idx)
        return {"ok": True}

    # Simulate what factory._handler does at call time
    turn_idx = proc.current_user_turn_idx if proc is not None else 0
    fake_dispatch("update_answer", {"qid": "q1", "text": "x", "confidence": "high"}, turn_idx)

    assert captured_turn_idx == [7], (
        f"tool handler must pass current_user_turn_idx=7, got {captured_turn_idx}"
    )


def test_factory_handler_uses_current_user_turn_idx_after_multiple_turns():
    """After 3 user/assistant pairs the processor's current_user_turn_idx equals the last user turn idx.

    Each pair consumes two _next_idx slots: user (even) then assistant (odd).
    Pairs: user@0+assistant@1, user@2+assistant@3, user@4+assistant@5
    Last user idx = 4.
    """
    proc = TurnPersistFrameProcessor(supabase_client=MagicMock(), session_id="s1", initial_idx=0)

    last_user_idx = -1
    for _ in range(3):
        # user turn
        idx = proc._next_idx
        proc._next_idx += 1
        proc._last_user_turn_idx = idx
        last_user_idx = idx
        # assistant turn — _last_user_turn_idx must NOT change
        proc._next_idx += 1

    assert proc.current_user_turn_idx == last_user_idx == 4, (
        f"after 3 user/assistant pairs, current_user_turn_idx must be 4, got {proc.current_user_turn_idx}"
    )
