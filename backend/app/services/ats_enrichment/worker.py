"""Throttled, sequential enrichment worker — one resume in memory at a time so a
burst of imported candidates can't blow the server. Picks pending candidates
(active-first, FIFO within a tier), processes each via the processor, and manages
status/retry/park. Lifespan task, gated by RUN_BACKGROUND_WORKERS AND
ATS_INTEGRATIONS_ENABLED. Mirrors ats_sync/drainer's isolation + park semantics."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog

from app.config import get_settings
from app.services.ats_enrichment.processor import process_candidate

logger = structlog.get_logger(__name__)

_CAND_COLS = "id, requisition_id, name, status, profile, enrichment_attempts"
# Fetch a window wider than the batch so the active-first sort can prioritize
# across more than just the oldest `batch` rows.
_FETCH_WINDOW = 25


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _fetch_pending(supabase, batch: int) -> list[dict]:
    window = max(batch, _FETCH_WINDOW)
    res = await (
        supabase.table("candidates")
        .select(_CAND_COLS)
        .eq("enrichment_status", "pending")
        .is_null("deleted_at")
        .order("created_at")
        .limit(window)
        .execute_async()
    )
    rows = res.data or []
    # Stable sort → active candidates first, created_at order preserved within a tier.
    rows.sort(key=lambda r: 0 if r.get("status") == "active" else 1)
    return rows[:batch]


async def _record_failure(supabase, row: dict, detail: str, max_retries: int) -> None:
    attempts = int(row.get("enrichment_attempts") or 0) + 1
    update: dict = {
        "enrichment_attempts": attempts,
        "enrichment_error": detail,
        "updated_at": _now(),
    }
    if attempts >= max_retries:
        update["enrichment_status"] = "failed"  # park — no longer selected
        logger.warning(
            "ats_enrichment_parked",
            extra={"candidate_id": row.get("id"), "detail": detail},
        )
    await supabase.table("candidates").update(update).eq("id", row["id"]).execute_async()


async def _mark_skipped(supabase, candidate_id: str) -> None:
    await (
        supabase.table("candidates")
        .update({"enrichment_status": "skipped", "updated_at": _now()})
        .eq("id", candidate_id)
        .execute_async()
    )


async def drain_enrichment_once(supabase, *, process=None) -> int:
    """One throttle tick: process up to BATCH pending candidates. 'done' is set by
    the ats_enrich_candidate RPC inside the processor; 'skipped' and failures are
    recorded here. Returns the count handled (done + skipped)."""
    process = process or process_candidate
    settings = get_settings()
    rows = await _fetch_pending(supabase, settings.ATS_ENRICHMENT_BATCH)
    handled = 0
    for row in rows:
        try:
            outcome = await process(supabase, row)
        except Exception as exc:  # noqa: BLE001 — one bad resume never kills the loop
            await _record_failure(
                supabase, row, str(exc)[:300], settings.ATS_ENRICHMENT_MAX_RETRIES
            )
            continue
        if outcome == "skipped":
            await _mark_skipped(supabase, row["id"])
        handled += 1
    return handled


async def run_ats_enrichment_worker(supabase) -> None:
    """Forever-loop; cancelled on app shutdown via the lifespan context."""
    interval = get_settings().ATS_ENRICHMENT_INTERVAL_S
    logger.info("ats_enrichment_worker_started", extra={"interval_s": interval})
    while True:
        try:
            handled = await drain_enrichment_once(supabase)
            if handled:
                logger.info("ats_enrichment_processed", extra={"n": handled})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("ats_enrichment_worker_error", extra={"error": str(exc)})
        await asyncio.sleep(interval)
