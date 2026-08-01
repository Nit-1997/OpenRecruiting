"""Characterization tests for the small lifespan background loops:
slack_token_refresh and intake_lock_cleanup. Each loop is driven exactly one
iteration by raising CancelledError on the second pass, so we exercise the body
without an infinite loop.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import intake_lock_cleanup, slack_token_refresh


# ----------------------- slack_token_refresh -----------------------

@pytest.mark.asyncio
async def test_slack_refresh_disabled_returns_immediately():
    with patch.object(
        slack_token_refresh, "get_settings",
        lambda: SimpleNamespace(SLACK_TOKEN_REFRESH_ENABLED=False),
    ):
        # Should return without ever touching the service.
        await slack_token_refresh.run_slack_token_refresh_loop()


@pytest.mark.asyncio
async def test_slack_refresh_runs_one_iteration_then_cancelled():
    settings = SimpleNamespace(
        SLACK_TOKEN_REFRESH_ENABLED=True,
        SLACK_TOKEN_REFRESH_INTERVAL_SECONDS=0,
        SLACK_TOKEN_REFRESH_LOOKAHEAD_SECONDS=900,
        SLACK_TOKEN_REFRESH_BATCH_SIZE=10,
    )
    service = MagicMock()
    service.refresh_expiring_installations = AsyncMock(return_value={"refreshed": 2, "failed": 0})

    with patch.object(slack_token_refresh, "get_settings", lambda: settings), \
         patch.object(slack_token_refresh, "get_slack_service", return_value=service), \
         patch.object(slack_token_refresh.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError)):
        with pytest.raises(asyncio.CancelledError):
            await slack_token_refresh.run_slack_token_refresh_loop()
    service.refresh_expiring_installations.assert_awaited_once()


@pytest.mark.asyncio
async def test_slack_refresh_swallows_transient_error():
    settings = SimpleNamespace(
        SLACK_TOKEN_REFRESH_ENABLED=True,
        SLACK_TOKEN_REFRESH_INTERVAL_SECONDS=0,
        SLACK_TOKEN_REFRESH_LOOKAHEAD_SECONDS=900,
        SLACK_TOKEN_REFRESH_BATCH_SIZE=10,
    )
    service = MagicMock()
    service.refresh_expiring_installations = AsyncMock(side_effect=RuntimeError("db blip"))

    sleeps = {"n": 0}

    async def fake_sleep(_):
        sleeps["n"] += 1
        raise asyncio.CancelledError

    with patch.object(slack_token_refresh, "get_settings", lambda: settings), \
         patch.object(slack_token_refresh, "get_slack_service", return_value=service), \
         patch.object(slack_token_refresh.asyncio, "sleep", fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            await slack_token_refresh.run_slack_token_refresh_loop()
    # The error did not crash the loop; it still reached the sleep.
    assert sleeps["n"] == 1


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
