"""Drain a Pipecat session gracefully.

Sequence:
  1. Queue EndFrame → Pipecat flushes in-flight TTS, propagates through pipeline.
     TurnPersistFrameProcessor (added in Phase 2) issues async DB writes.
  2. Sleep safety_timeout_s to let the EndFrame and async writes settle.
  3. Force task.cancel() as the safety net — same pattern as
     voice-agent/src/main.py:521-526 (8s timeout in v1, 8s default here).
  4. Unregister from session registry.

Notes on Pipecat APIs:
  - `EndFrame` is the *graceful* shutdown signal. There is no public
    `wait_for_idle()` — the pipeline just propagates EndFrame end-to-end,
    closes the transport (which emits `on_client_disconnected`), and stops.
  - `task.cancel()` is the *hard* shutdown — used as a safety net when
    EndFrame doesn't propagate within the budget.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from pipecat.frames.frames import EndFrame

from .session_registry import SessionRegistry, SessionNotFound

logger = structlog.get_logger(__name__)


DEFAULT_SAFETY_TIMEOUT_S = 8.0
"""Time we wait between sending EndFrame and force-cancelling the task.
Tuned to match v1's drain budget. Voice agent should always shut down well
before this; the cancel is purely insurance."""


async def drain_session(
    registry: SessionRegistry,
    session_id: str,
    safety_timeout_s: float = DEFAULT_SAFETY_TIMEOUT_S,
) -> dict[str, Any]:
    """Drain the Pipecat session for `session_id` and return a result dict.

    Raises SessionNotFound if no task is registered.
    """
    task = registry.get(session_id)
    start = time.monotonic()

    forced_cancel = False
    try:
        logger.info("drain_start", session_id=session_id)
        await task.queue_frames([EndFrame()])
    except Exception as e:
        logger.warning(
            "drain_queue_endframe_failed",
            session_id=session_id,
            error=str(e),
        )

    # Wait for the EndFrame to propagate through the pipeline. We sleep instead
    # of waiting on a specific Pipecat future because the public API does not
    # expose one. safety_timeout_s is also our hard ceiling — if the pipeline
    # is hung we force-cancel after this window.
    await asyncio.sleep(safety_timeout_s)

    try:
        await task.cancel()
        forced_cancel = True
    except Exception as e:
        # task.cancel() raising means the task is already dead — fine.
        logger.info("drain_cancel_already_done", session_id=session_id, error=str(e))

    registry.unregister(session_id)

    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "drain_complete",
        session_id=session_id,
        duration_ms=duration_ms,
        forced_cancel=forced_cancel,
    )
    return {"drained": True, "duration_ms": duration_ms, "forced_cancel": forced_cancel}
