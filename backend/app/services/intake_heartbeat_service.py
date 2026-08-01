"""
Heartbeat ping for the intake voice/text session lock.

Frontend calls this every 30s while live and every 60s while paused.
If the modality lock is no longer held by the caller, the RPC raises
`heartbeat_no_lock`, which surfaces as a 409 on the API side so the
client can stop pinging.
"""
from __future__ import annotations

from uuid import UUID

import structlog

logger = structlog.get_logger(__name__)


class HeartbeatNoLockError(Exception):
    """The session's modality lock is not held by this caller."""


class IntakeHeartbeatService:
    def __init__(self, supabase_client):
        self.supa = supabase_client

    async def ping(self, *, session_id: UUID, user_id: UUID, paused: bool) -> str:
        try:
            # This wrapper's .rpc() is async and IS the execution — await it
            # directly. A chained .execute() hits the coroutine and raises
            # "AttributeError: 'coroutine' object has no attribute 'execute'"
            # → 500 (the bug behind the heartbeat CORS errors). Same fix as
            # lobby_chat_service.append_message.
            resp = await self.supa.rpc(
                "intake_session_heartbeat",
                {
                    "p_session_id": str(session_id),
                    "p_user_id": str(user_id),
                    "p_paused": paused,
                },
            )
        except Exception as e:
            if "heartbeat_no_lock" in str(e):
                raise HeartbeatNoLockError(str(e)) from e
            raise
        last_at = getattr(resp, "data", resp)
        logger.debug(
            "intake_heartbeat",
            session_id=str(session_id),
            paused=paused,
            last_at=last_at,
        )
        return last_at
