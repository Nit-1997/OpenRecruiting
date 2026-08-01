"""Tests for intake_heartbeat_service."""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.intake_heartbeat_service import (
    IntakeHeartbeatService,
    HeartbeatNoLockError,
)


@pytest.fixture
def supa():
    # The service awaits self.supa.rpc(...) directly (it IS the execution);
    # there is no chained .execute(). Mirror that contract with an AsyncMock.
    c = MagicMock()
    c.rpc = AsyncMock()
    return c


async def test_ping_returns_timestamp_when_lock_held(supa):
    supa.rpc.return_value = MagicMock(data="2026-05-28T10:00:00+00:00")
    svc = IntakeHeartbeatService(supa)
    ts = await svc.ping(session_id=uuid4(), user_id=uuid4(), paused=False)
    assert ts == "2026-05-28T10:00:00+00:00"
    supa.rpc.assert_called_once()
    args, kwargs = supa.rpc.call_args
    assert args[0] == "intake_session_heartbeat"


async def test_ping_raises_when_no_lock(supa):
    supa.rpc.side_effect = Exception("heartbeat_no_lock")
    svc = IntakeHeartbeatService(supa)
    with pytest.raises(HeartbeatNoLockError):
        await svc.ping(session_id=uuid4(), user_id=uuid4(), paused=False)


async def test_ping_passes_paused_flag(supa):
    supa.rpc.return_value = MagicMock(data="2026-05-28T10:00:00+00:00")
    svc = IntakeHeartbeatService(supa)
    await svc.ping(session_id=uuid4(), user_id=uuid4(), paused=True)
    args, _ = supa.rpc.call_args
    assert args[1]["p_paused"] is True
