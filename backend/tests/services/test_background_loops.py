"""Characterization tests for the intake_lock_cleanup lifespan background loop.
The loop is driven exactly one iteration by raising CancelledError on the second
pass, so we exercise the body without an infinite loop.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import intake_lock_cleanup


# ----------------------- intake_lock_cleanup -----------------------

@pytest.mark.asyncio
async def test_release_stale_locks_once_returns_count():
    sb = MagicMock()
    sb.rpc = AsyncMock(return_value=SimpleNamespace(data=7))
    n = await intake_lock_cleanup.release_stale_locks_once(sb, stale_minutes=5)
    assert n == 7
    sb.rpc.assert_awaited_once_with(
        "release_stale_intake_modality_locks", {"p_stale_minutes": 5}
    )


@pytest.mark.asyncio
async def test_release_stale_locks_once_handles_none_data():
    sb = MagicMock()
    sb.rpc = AsyncMock(return_value=SimpleNamespace(data=None))
    assert await intake_lock_cleanup.release_stale_locks_once(sb, stale_minutes=5) == 0


@pytest.mark.asyncio
async def test_cleanup_loop_one_iteration_with_releases():
    sb = MagicMock()
    sb.rpc = AsyncMock(return_value=SimpleNamespace(data=3))
    with patch.object(intake_lock_cleanup.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError)):
        with pytest.raises(asyncio.CancelledError):
            await intake_lock_cleanup.run_stale_lock_cleanup_loop(sb)
    sb.rpc.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_loop_swallows_error():
    sb = MagicMock()
    sb.rpc = AsyncMock(side_effect=RuntimeError("blip"))
    sleeps = {"n": 0}

    async def fake_sleep(_):
        sleeps["n"] += 1
        raise asyncio.CancelledError

    with patch.object(intake_lock_cleanup.asyncio, "sleep", fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            await intake_lock_cleanup.run_stale_lock_cleanup_loop(sb)
    assert sleeps["n"] == 1
