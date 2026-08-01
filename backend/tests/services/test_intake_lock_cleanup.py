"""Tests for intake_lock_cleanup."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.intake_lock_cleanup import release_stale_locks_once


@pytest.fixture
def supa():
    c = MagicMock()
    # .rpc() is async on the SupabaseAdminClient wrapper — it IS the execution.
    c.rpc = AsyncMock(return_value=MagicMock(data=3))
    return c


async def test_release_stale_locks_once_returns_count(supa):
    n = await release_stale_locks_once(supa, stale_minutes=5)
    assert n == 3
    supa.rpc.assert_awaited_once()
    args, _kwargs = supa.rpc.call_args
    assert args[0] == "release_stale_intake_modality_locks"
    assert args[1]["p_stale_minutes"] == 5


async def test_release_stale_locks_once_returns_zero_when_none(supa):
    supa.rpc = AsyncMock(return_value=MagicMock(data=0))
    assert await release_stale_locks_once(supa, stale_minutes=5) == 0


async def test_release_stale_locks_once_returns_zero_on_null(supa):
    supa.rpc = AsyncMock(return_value=MagicMock(data=None))
    assert await release_stale_locks_once(supa, stale_minutes=5) == 0
