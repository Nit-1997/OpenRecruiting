"""
Background loop that proactively refreshes expiring Slack installation tokens.

Ported from the v1 `workers/slack_token_refresh_worker.py` (which used
APScheduler) into v2's lifespan-task style so v2 is self-sufficient once v1
retires. Without this, Slack tokens silently expire — the refresh *logic* lives
in `slack_service.refresh_expiring_installations`, but nothing was calling it on
a schedule in v2.

Started by the FastAPI lifespan; gated on SLACK_TOKEN_REFRESH_ENABLED; runs once
per SLACK_TOKEN_REFRESH_INTERVAL_SECONDS.
"""
from __future__ import annotations

import asyncio

import structlog

from app.config import get_settings
from app.services.slack_service import get_slack_service

logger = structlog.get_logger(__name__)


async def run_slack_token_refresh_loop() -> None:
    """Forever-loop. Cancelled on app shutdown via the lifespan context."""
    settings = get_settings()
    if not settings.SLACK_TOKEN_REFRESH_ENABLED:
        logger.info("slack_token_refresh_disabled")
        return

    interval = settings.SLACK_TOKEN_REFRESH_INTERVAL_SECONDS
    logger.info("slack_token_refresh_started", interval_s=interval)
    service = get_slack_service()
    while True:
        try:
            result = await service.refresh_expiring_installations(
                lookahead_seconds=settings.SLACK_TOKEN_REFRESH_LOOKAHEAD_SECONDS,
                batch_size=settings.SLACK_TOKEN_REFRESH_BATCH_SIZE,
            )
            if result and any(result.values()):
                logger.info("slack_tokens_refreshed", **result)
        except asyncio.CancelledError:
            logger.info("slack_token_refresh_cancelled")
            raise
        except Exception as e:
            # Never crash the loop on a transient Slack/DB blip.
            logger.warning("slack_token_refresh_error", error=str(e))
        await asyncio.sleep(interval)
