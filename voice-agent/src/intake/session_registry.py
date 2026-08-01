"""In-process registry of active Pipecat PipelineTask objects, keyed by intake
session_id. Used by the drain endpoint to look up the running task and shut it
down gracefully.

Lifecycle (managed by main.py):
  - register(session_id, task)  — when WebRTC offer arrives and pipeline starts
  - unregister(session_id)      — when on_client_disconnected fires (or drain runs)

Thread-safety: voice agent process is single-asyncio-loop. No lock needed.
"""

from __future__ import annotations

from typing import Any
import structlog

logger = structlog.get_logger(__name__)


class SessionNotFound(LookupError):
    """Raised by drain when no task is registered for the requested session_id."""


class SessionRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, Any] = {}

    def register(self, session_id: str, task: Any) -> None:
        if session_id in self._tasks:
            logger.warning("session_replaced_in_registry", session_id=session_id)
        self._tasks[session_id] = task

    def get(self, session_id: str) -> Any:
        try:
            return self._tasks[session_id]
        except KeyError:
            raise SessionNotFound(f"no active pipeline task for session {session_id}")

    def unregister(self, session_id: str) -> None:
        self._tasks.pop(session_id, None)
