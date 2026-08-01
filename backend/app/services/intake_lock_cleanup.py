"""
Background loop that releases intake_sessions.active_modality locks
that haven't been heartbeated in N minutes.

Started by the FastAPI lifespan; runs once per 60s; SECURITY DEFINER
RPC does the actual UPDATE under service_role.
"""
from __future__ import annotations

import asyncio

import structlog

logger = structlog.get_logger(__name__)

_CRON_INTERVAL_S = 60
_STALE_MINUTES = 5


async def release_stale_locks_once(supabase_client, *, stale_minutes: int) -> int:
    # The wrapper's .rpc() is async and IS the execution — await it directly
    # (no chained .execute(), which hit a coroutine and raised AttributeError).
    resp = await supabase_client.rpc(
        "release_stale_intake_modality_locks",
        {"p_stale_minutes": stale_minutes},
    )
    return int(resp.data or 0)


async def run_stale_lock_cleanup_loop(supabase_client) -> None:
    """Forever-loop. Cancelled on app shutdown via the lifespan context."""
    logger.info("intake_lock_cleanup_started", interval_s=_CRON_INTERVAL_S)
    while True:
        try:
            n = await release_stale_locks_once(
                supabase_client, stale_minutes=_STALE_MINUTES
            )
            if n > 0:
                logger.info("intake_locks_released_total", n=n)
        except asyncio.CancelledError:
            logger.info("intake_lock_cleanup_cancelled")
            raise
        except Exception as e:
            # Never crash the loop on a transient DB blip.
            logger.warning("intake_lock_cleanup_error", error=str(e))
        await asyncio.sleep(_CRON_INTERVAL_S)
