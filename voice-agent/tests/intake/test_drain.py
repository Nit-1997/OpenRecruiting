"""Drain handler — queues EndFrame on the matching PipelineTask, with safety cancel."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.intake.drain import drain_session
from src.intake.session_registry import SessionRegistry, SessionNotFound


@pytest.mark.asyncio
async def test_drain_session_queues_end_frame_and_returns_ok():
    reg = SessionRegistry()
    task = MagicMock()
    task.queue_frames = AsyncMock()
    task.cancel = AsyncMock()
    reg.register(session_id="s1", task=task)
    with patch("src.intake.drain.asyncio.sleep", new=AsyncMock()):
        result = await drain_session(registry=reg, session_id="s1", safety_timeout_s=0.0)
    assert result["drained"] is True
    task.queue_frames.assert_awaited_once()
    # First positional arg is the list of frames
    frames = task.queue_frames.call_args.args[0]
    assert any(type(f).__name__ == "EndFrame" for f in frames)


@pytest.mark.asyncio
async def test_drain_session_unknown_raises():
    reg = SessionRegistry()
    with pytest.raises(SessionNotFound):
        await drain_session(registry=reg, session_id="nope")


@pytest.mark.asyncio
async def test_drain_session_safety_cancel_fires_on_timeout():
    """If the pipeline doesn't shut down within safety_timeout_s, we call task.cancel()."""
    reg = SessionRegistry()
    task = MagicMock()
    task.queue_frames = AsyncMock()
    task.cancel = AsyncMock()
    reg.register(session_id="s1", task=task)
    result = await drain_session(registry=reg, session_id="s1", safety_timeout_s=0.01)
    task.queue_frames.assert_awaited_once()
    task.cancel.assert_awaited_once()
    assert result["drained"] is True
    assert result["forced_cancel"] is True


@pytest.mark.asyncio
async def test_drain_session_unregisters_after_drain():
    reg = SessionRegistry()
    task = MagicMock()
    task.queue_frames = AsyncMock()
    task.cancel = AsyncMock()
    reg.register(session_id="s1", task=task)
    with patch("src.intake.drain.asyncio.sleep", new=AsyncMock()):
        await drain_session(registry=reg, session_id="s1", safety_timeout_s=0.0)
    with pytest.raises(SessionNotFound):
        reg.get("s1")
