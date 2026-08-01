import json
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)

FORCE_PUBLISH_MAX_ROWS = 10000

ProgressCallback = Callable[[int, int, int], Awaitable[None]]


class BrainSyncCron:
    """In-process scheduler jobs that drain cortex_events to SQS.

    publish_settled_events: scans for rows past the 48h settledness window and emits.
    publish_org_now: on-demand force-publish for one org, ignoring the window.
    reconcile: weekly safety net that re-nudges cortex_events for any settled
    Supabase rows that have no IngestionRecord.
    """

    def __init__(
        self,
        supabase: Any,
        sqs_client: Any,
        queue_url: str,
        settledness_window_hours: int = 48,
        batch_size: int = 1000,
    ):
        self._supabase = supabase
        self._sqs = sqs_client
        self._queue_url = queue_url
        self._window_hours = settledness_window_hours
        self._batch_size = batch_size

    async def _publish_event_row(self, row: dict) -> None:
        """Send one cortex_events row to SQS and stamp published_at/publish_count.

        Shared by the cron publisher and the on-demand force-publish path so the
        two stay identical. Raises on any failure; the caller decides whether to
        continue with the next row or abort.
        """
        next_publish_count = int(row.get("publish_count", 0)) + 1
        self._sqs.send_message(
            QueueUrl=self._queue_url,
            MessageGroupId=f"{row['event_type']}:{row['source_id']}",
            MessageDeduplicationId=f"{row['id']}:{row['last_touch_at']}",
            MessageBody=json.dumps({
                "event_type": row["event_type"],
                "source_id": str(row["source_id"]),
                "org_id": str(row["org_id"]),
                "last_touch_at": row["last_touch_at"],
                "publish_count": next_publish_count,
                "event_pk": str(row["id"]),
            }),
        )
        await (
            self._supabase.table("cortex_events")
            .update({
                "published_at": datetime.now(timezone.utc).isoformat(),
                "publish_count": next_publish_count,
            })
            .eq("id", row["id"])
            .execute()
        )

    async def publish_settled_events(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self._window_hours)
        resp = await self._supabase.rpc(
            "cortex_events_settled",
            {"cutoff": cutoff.isoformat(), "limit": self._batch_size},
        ).execute()

        rows = resp.data or []
        sent = 0
        for row in rows:
            try:
                await self._publish_event_row(row)
                sent += 1
            except Exception as e:
                logger.error(
                    "publish_failed",
                    event_pk=row["id"],
                    event_type=row["event_type"],
                    error=str(e),
                )
        logger.info("publish_settled_events_complete", sent=sent, scanned=len(rows))
        return sent

    async def publish_org_now(
        self,
        org_id: str,
        on_progress: ProgressCallback | None = None,
    ) -> dict:
        """Force-publish all unpublished/restamped cortex_events for one org.

        Used for on-demand support flushes. Bypasses the 48h settledness window
        so events can be ingested immediately rather than at the next cron tick.

        Eligibility (`published_at IS NULL OR last_touch_at > published_at`) is
        a column-vs-column comparison, which PostgREST URL filters cannot
        express — `last_touch_at.gt.published_at` would compare against the
        literal string `'published_at'`. We call the SQL RPC
        `cortex_events_for_org_unpublished` instead (migration 75), which
        mirrors `cortex_events_settled` (72) without the time cutoff and
        scopes to one org.

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

            resp = await self._supabase.rpc(
                "cortex_events_for_org_unpublished",
                {"p_org_id": org_id, "p_limit": page_limit},
            ).execute()
            rows = resp.data or []
            if not rows:
                break

            new_rows = [r for r in rows if str(r["id"]) not in seen_ids]
            if not new_rows:
                logger.warning(
                    "publish_org_now_no_progress",
                    org_id=org_id,
                    batch_rows=len(rows),
                    scanned=total_scanned,
                    published=total_published,
                )
                break

            batches += 1
            for row in new_rows:
                seen_ids.add(str(row["id"]))
                total_scanned += 1
                try:
                    await self._publish_event_row(row)
                    total_published += 1
                except Exception as e:
                    errors.append(f"event_pk={row['id']}: {str(e)[:120]}")
                    logger.error(
                        "force_publish_failed",
                        event_pk=row["id"],
                        event_type=row["event_type"],
                        org_id=org_id,
                        error=str(e),
                    )

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
            "publish_org_now_complete",
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
        force a cortex_events upsert so the publisher re-drains them next night.
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
