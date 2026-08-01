"""Drain the ats_webhook_events ledger: oldest-first, bounded batch,
per-event isolation. The receiver only persists; THIS is where events apply.

Parking semantics: a non-terminal event (failed/orphaned) retries on later
passes via retry_count; when the count reaches ATS_SYNC_MAX_RETRIES the row
is marked processed WITH its error retained — visible in /sync-status as a
failed event, and the pending fetch (processed_at IS NULL) never starves."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.config import get_settings
from app.logging_config import get_logger
from app.services.ats_sync.handlers import apply_event

logger = get_logger(__name__)

_TERMINAL = {"applied", "applied_with_skip", "bookkeeping", "ignored"}


async def drain_once(supabase) -> int:
    settings = get_settings()
    result = await (
        supabase.table("ats_webhook_events")
        .select("event_id, event_type, integration_id, payload, retry_count")
        .is_null("processed_at")
        .order("received_at")
        .limit(settings.ATS_SYNC_DRAIN_BATCH)
        .execute_async()
    )
    rows = result.data or []
    handled = 0
    for row in rows:
        now = datetime.now(timezone.utc).isoformat()
        try:
            outcome = await apply_event(supabase, row)
            outcome_status, detail = outcome.status, outcome.detail
        except Exception as exc:  # hard failure — never kills the batch
            outcome_status, detail = "failed", str(exc)[:300]

        if outcome_status in _TERMINAL:
            update: dict = {"processed_at": now}
            if detail:
                update["processing_error"] = detail
            await (
                supabase.table("ats_webhook_events")
                .update(update)
                .eq("event_id", row["event_id"])
                .execute_async()
            )
            handled += 1
            continue

        # failed | orphaned → retry on a later pass; park at the budget.
        new_count = int(row.get("retry_count") or 0) + 1
        update = {"retry_count": new_count, "processing_error": detail}
        if new_count >= settings.ATS_SYNC_MAX_RETRIES:
            update["processed_at"] = now
            logger.warning(
                "ats_sync_event_parked",
                extra={
                    "event": "ats_sync_event_parked",
                    "event_id": row["event_id"],
                    "detail": detail,
                },
            )
        else:
            logger.warning(
                "ats_sync_event_retry",
                extra={
                    "event": "ats_sync_event_retry",
                    "event_id": row["event_id"],
                    "status": outcome_status,
                    "retry_count": new_count,
                    "detail": detail,
                },
            )
        await (
            supabase.table("ats_webhook_events")
            .update(update)
            .eq("event_id", row["event_id"])
            .execute_async()
        )
    return handled


async def run_ats_sync_drainer(supabase) -> None:
    """Forever-loop; cancelled on app shutdown via the lifespan context."""
    interval = get_settings().ATS_SYNC_DRAIN_INTERVAL_S
    logger.info("ats_sync_drainer_started", extra={"interval_s": interval})
    while True:
        try:
            handled = await drain_once(supabase)
            if handled:
                logger.info(
                    "ats_sync_events_applied",
                    extra={"event": "ats_sync_events_applied", "n": handled},
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "ats_sync_drainer_error",
                extra={"event": "ats_sync_drainer_error", "error": str(exc)},
            )
        await asyncio.sleep(interval)
