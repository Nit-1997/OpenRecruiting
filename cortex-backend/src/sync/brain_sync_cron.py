from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import structlog

from src.sync.event_queue import ClaimedEvent, EventQueue
from src.sync.event_processor import EventProcessor

logger = structlog.get_logger(__name__)

FORCE_PUBLISH_MAX_ROWS = 10000

ProgressCallback = Callable[[int, int, int], Awaitable[None]]


class BrainSyncCron:
    """In-process scheduler jobs that drain cortex_events into the graph.

    process_settled_events: claims rows past the 48h settledness window and ingests them.
    process_org_now: on-demand force-ingest for one org, ignoring the window.
    reconcile: weekly safety net that re-nudges cortex_events for any settled
    Supabase rows that have no IngestionRecord.
    """

    def __init__(
        self,
        supabase: Any,
        queue: EventQueue,
        processor: EventProcessor,
        settledness_window_hours: int = 48,
        batch_size: int = 1000,
    ):
        self._supabase = supabase
        self._queue = queue
        self._processor = processor
        self._window_hours = settledness_window_hours
        self._batch_size = batch_size

    async def _process_one(
        self, event: ClaimedEvent, errors: list[str] | None = None
    ) -> bool:
        """Returns True on success. Never raises: one poisoned row must not
        stop the batch, and the queue records the failure for the retry.

        `errors` is an optional sink so force-publish can report the causes in
        its job record rather than only in the logs.
        """
        try:
            await self._processor.process(event)
        except Exception as e:
            logger.warning(
                "event_processing_failed",
                event_id=event.id,
                event_type=event.event_type,
                source_id=event.source_id,
                error=str(e),
            )
            if errors is not None:
                errors.append(f"event_pk={event.id}: {str(e)[:120]}")
            await self._queue.mark_failed(event.id, str(e))
            return False
        # Stamp the claimed row's own last_touch_at, never an app-clock now():
        # an edit landing between claim and completion would otherwise be older
        # than the stamp, fail `last_touch_at > completed_at`, and never re-queue.
        await self._queue.mark_done(event.id, event.last_touch_at)
        return True

    async def process_settled_events(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self._window_hours)
        events = await self._queue.claim_batch(limit=self._batch_size, cutoff=cutoff)
        succeeded = 0
        for event in events:
            if await self._process_one(event):
                succeeded += 1
        if events:
            logger.info("settled_events_processed", claimed=len(events), succeeded=succeeded)
        return succeeded

    async def process_org_now(
        self,
        org_id: str,
        on_progress: ProgressCallback | None = None,
    ) -> dict:
        """Force-ingest every unfinished/restamped cortex_events row for one org.

        Used for on-demand support flushes. Passing `cutoff=None` bypasses the
        48h settledness window so events land in the graph now rather than at
        the next poll.

        `published` in the returned dict now counts rows actually ingested, not
        rows handed to a queue — there is no longer a gap between the two.

        on_progress, if provided, is awaited after each batch with the cumulative
        (scanned, published, batches) so async callers (e.g. job tracker) can
        write live progress to durable storage.

        Caps at FORCE_PUBLISH_MAX_ROWS per call to bound request duration.
        """
        total_scanned = 0
        total_published = 0
        errors: list[str] = []
        batches = 0
        seen_ids: set[str] = set()

        while total_scanned < FORCE_PUBLISH_MAX_ROWS:
            remaining = FORCE_PUBLISH_MAX_ROWS - total_scanned
            page_limit = min(self._batch_size, remaining)

            events = await self._queue.claim_batch(
                limit=page_limit, cutoff=None, org_id=org_id
            )
            if not events:
                break

            # A failed row keeps its lease only until it expires; a short lease
            # can hand back the same id, so stop rather than spin on it.
            fresh = [e for e in events if e.id not in seen_ids]
            if not fresh:
                logger.warning(
                    "process_org_now_no_progress",
                    org_id=org_id,
                    batch_rows=len(events),
                    scanned=total_scanned,
                    published=total_published,
                )
                break

            batches += 1
            for event in fresh:
                seen_ids.add(event.id)
                total_scanned += 1
                if await self._process_one(event, errors=errors):
                    total_published += 1

            if on_progress is not None:
                try:
                    await on_progress(total_scanned, total_published, batches)
                except Exception as e:
                    logger.warning(
                        "force_publish_progress_callback_failed",
                        org_id=org_id,
                        error=str(e),
                    )

        logger.info(
            "process_org_now_complete",
            org_id=org_id,
            scanned=total_scanned,
            published=total_published,
            errors=len(errors),
            batches=batches,
        )
        return {
            "scanned": total_scanned,
            "published": total_published,
            "batches": batches,
            "errors": errors[:50],
        }

    async def reconcile(self) -> int:
        """Weekly safety net.

        For each high-finality state in source tables, find rows that are
        eligible for ingestion but absent from cortex_ingestion_record, and
        force a cortex_events upsert so the next poll re-drains them.
        """
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
        sql_pairs = [
            (
                "feedback_debrief_available",
                f"""
                SELECT cr.id AS source_id,
                       (SELECT r.organization_id FROM rounds rnd
                          JOIN requisitions r ON r.id = rnd.requisition_id
                          WHERE rnd.id = cr.round_id) AS org_id,
                       cr.processing_completed_at AS last_touch_at
                FROM candidate_rounds cr
                LEFT JOIN cortex_ingestion_record ir
                  ON ir.event_type = 'feedback_debrief_available' AND ir.source_id = cr.id
                WHERE cr.processing_status = 'completed'
                  AND cr.processing_completed_at < '{cutoff_iso}'
                  AND ir.id IS NULL
                LIMIT 500
                """,
            ),
            (
                "intake_transcript_available",
                f"""
                SELECT r.id AS source_id, r.organization_id AS org_id,
                       r.intake_processing_completed_at AS last_touch_at
                FROM requisitions r
                LEFT JOIN cortex_ingestion_record ir
                  ON ir.event_type = 'intake_transcript_available' AND ir.source_id = r.id
                WHERE r.intake_processing_status = 'completed'
                  AND r.intake_processing_completed_at < '{cutoff_iso}'
                  AND ir.id IS NULL
                LIMIT 500
                """,
            ),
        ]

        nudged = 0
        for event_type, sql in sql_pairs:
            resp = await self._supabase.rpc(
                "execute_readonly_query", {"query": sql}
            ).execute()
            rows = resp.data or []
            for row in rows:
                if not row.get("org_id"):
                    continue
                await (
                    self._supabase.table("cortex_events")
                    .upsert({
                        "event_type": event_type,
                        "source_id": str(row["source_id"]),
                        "org_id": str(row["org_id"]),
                        "source_table": "reconciliation",
                        "payload_keys": {},
                        "last_touch_at": datetime.now(timezone.utc).isoformat(),
                    }, on_conflict="event_type,source_id")
                    .execute()
                )
                nudged += 1

        logger.info("reconciliation_complete", nudged=nudged)
        return nudged
