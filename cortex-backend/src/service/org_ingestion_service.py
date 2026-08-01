from __future__ import annotations

import structlog
from time import monotonic
from typing import Awaitable, Callable

from supabase import AsyncClient

from src.model.ingestion import SourceRef
from src.service.event_router import EventRouter
from src.service.ingestion_tracker import IngestionTracker
from src.service.supabase_fetcher import SupabaseFetcher

logger = structlog.get_logger(__name__)

BATCH_SIZE = 100

ProgressCallback = Callable[..., Awaitable[None]]

STRUCTURED_EVENTS = [
    ("plan_created", "requisition"),
    ("feedback_completed", "candidate_round"),
    ("decision_made", "candidate"),
]

EPISODIC_EVENTS = [
    ("question_summaries_available", "candidate_round"),
    ("feedback_debrief_available", "candidate_round"),
    ("interview_transcript_available", "candidate_round"),
    ("intake_transcript_available", "requisition"),
    ("jd_available", "requisition"),
]


class OrgIngestionService:
    def __init__(self, fetcher: SupabaseFetcher, event_router: EventRouter, tracker: IngestionTracker | None = None):
        self._fetcher = fetcher
        self._event_router = event_router
        self._tracker = tracker

    async def discover(self, org_id: str) -> dict:
        client = await self._fetcher._get_client()

        req_resp = await client.table("requisitions").select("id, updated_at").eq("organization_id", org_id).is_("deleted_at", "null").execute()
        req_rows = req_resp.data or []
        requisition_ids = [r["id"] for r in req_rows]

        if not requisition_ids:
            return self._empty_discovery()

        round_ids = await self._round_ids_for_requisitions(client, requisition_ids)
        if not round_ids:
            return self._empty_discovery(requisition_ids=[(r["id"], r.get("updated_at")) for r in req_rows])

        candidate_rounds = await self._batched_in_query(
            client, "candidate_rounds", "id, candidate_id, rating, round_id, updated_at", "round_id", round_ids,
        )
        cr_ids = [cr["id"] for cr in candidate_rounds]

        cr_with_qs_rows = await self._batched_in_query(
            client, "candidate_rounds", "id, updated_at", "round_id", round_ids,
            extra_filter=lambda q: q.not_.is_("question_summaries", "null"),
        )

        if cr_ids:
            segment_rows = await self._batched_in_query(
                client, "transcripts", "candidate_round_id, created_at", "candidate_round_id", cr_ids,
                extra_filter=lambda q: q.not_.is_("segments", "null"),
            )

            fb_rows = await self._batched_in_query(
                client, "transcripts", "candidate_round_id, created_at", "candidate_round_id", cr_ids,
                extra_filter=lambda q: q.not_.is_("feedback_transcript", "null"),
            )
        else:
            segment_rows = []
            fb_rows = []

        cand_ids = list({cr["candidate_id"] for cr in candidate_rounds})
        if cand_ids:
            decision_rows = await self._batched_in_query(
                client, "candidates", "id, status, requisition_id, updated_at", "id", cand_ids,
                extra_filter=lambda q: q.in_("status", ["hired", "rejected", "withdrawn"]).is_("deleted_at", "null"),
            )
        else:
            decision_rows = []

        req_intake_rows = await self._batched_in_query(
            client, "requisitions", "id, updated_at", "id", requisition_ids,
            extra_filter=lambda q: q.not_.is_("intake_transcript", "null"),
        )

        req_jd_rows = await self._batched_in_query(
            client, "requisitions", "id, updated_at", "id", requisition_ids,
            extra_filter=lambda q: q.not_.is_("job_description", "null"),
        )

        return {
            "requisition_ids": [(r["id"], r.get("updated_at")) for r in req_rows],
            "cr_all": [(cr["id"], cr.get("updated_at")) for cr in candidate_rounds],
            "decision_candidates": [(c, c.get("updated_at")) for c in decision_rows],
            "cr_with_question_summaries": [(cr["id"], cr.get("updated_at")) for cr in cr_with_qs_rows],
            "cr_with_feedback_transcript": [(t["candidate_round_id"], t.get("created_at")) for t in fb_rows],
            "cr_with_segments": [(t["candidate_round_id"], t.get("created_at")) for t in segment_rows],
            "req_with_intake": [(r["id"], r.get("updated_at")) for r in req_intake_rows],
            "req_with_jd": [(r["id"], r.get("updated_at")) for r in req_jd_rows],
        }

    def _empty_discovery(self, requisition_ids=None):
        return {
            "requisition_ids": requisition_ids or [],
            "cr_all": [], "decision_candidates": [],
            "cr_with_question_summaries": [], "cr_with_segments": [],
            "cr_with_feedback_transcript": [], "req_with_intake": [], "req_with_jd": [],
        }

    async def ingest_org(
        self,
        org_id: str,
        progress_callback: ProgressCallback | None = None,
        events_total_callback: Callable[[int], Awaitable[None]] | None = None,
        heartbeat_interval_seconds: float = 5.0,
    ) -> dict:
        """Run the full org ingest.

        Args:
            org_id: org to ingest.
            progress_callback: called after each event with throttling (no more
                than once per `heartbeat_interval_seconds`) AND unconditionally
                after each event-type loop completes. kwargs are
                (current_event_type, events_processed, events_skipped,
                nodes_created, edges_created, errors_count, event_counts).
                The per-item heartbeat is required for accurate stale-job
                recovery: a single slow event-type loop (e.g. 100 transcripts
                at 5 s each = 8+ min) would otherwise let updated_at stall past
                the stale threshold and cause a retry to spawn a duplicate.
                If None, no progress reporting (sync /ingest/org behavior).
            events_total_callback: called once with the discovered event total
                before processing begins. Lets the async wrapper transition the
                job from 'pending' to 'running' with events_total populated.
            heartbeat_interval_seconds: minimum gap between per-item progress
                writes. Trades DB load for staleness-detection granularity.
        """
        discovery = await self.discover(org_id)
        total_nodes = 0
        total_edges = 0
        total_errors: list[str] = []
        event_counts: dict[str, dict] = {}
        events_processed = 0
        events_skipped = 0
        last_heartbeat_at = monotonic()

        events_total = (
            len(discovery.get("requisition_ids", []))
            + len(discovery.get("cr_all", []))
            + len(discovery.get("decision_candidates", []))
            + len(discovery.get("cr_with_question_summaries", []))
            + len(discovery.get("cr_with_feedback_transcript", []))
            + len(discovery.get("cr_with_segments", []))
            + len(discovery.get("req_with_intake", []))
            + len(discovery.get("req_with_jd", []))
        )
        if events_total_callback:
            await events_total_callback(events_total)

        async def _heartbeat(current: str) -> None:
            """Throttled per-item progress write. Fires the callback only if at
            least heartbeat_interval_seconds have elapsed since the last fire.
            This keeps updated_at fresh enough that the job-service stale
            recovery (15 min) doesn't kill a healthy long-running ingest."""
            nonlocal last_heartbeat_at
            if not progress_callback:
                return
            now = monotonic()
            if (now - last_heartbeat_at) < heartbeat_interval_seconds:
                return
            last_heartbeat_at = now
            await progress_callback(
                current_event_type=current,
                events_processed=events_processed,
                events_skipped=events_skipped,
                nodes_created=total_nodes,
                edges_created=total_edges,
                errors_count=len(total_errors),
                event_counts=event_counts,
            )

        async def _run(event_type: str, source_ref: SourceRef, label: str, updated_at: str | None = None):
            nonlocal total_nodes, total_edges, events_processed, events_skipped
            ec = event_counts.setdefault(event_type, {"nodes": 0, "edges": 0, "processed": 0, "skipped": 0, "errors": 0})

            source_id = source_ref.candidate_round_id or source_ref.requisition_id or source_ref.candidate_id
            if updated_at and self._tracker and source_id:
                if await self._tracker.is_ingested(event_type, source_id, updated_at):
                    ec["skipped"] += 1
                    events_skipped += 1
                    logger.debug("skipping_already_ingested", event_type=event_type, source_id=source_id)
                    return

            handler = self._event_router.get_handler(event_type)
            if handler is None:
                total_errors.append(f"no handler for {event_type}")
                return
            try:
                t0 = monotonic()
                result = await handler.handle(source_ref, org_id)
                elapsed_ms = (monotonic() - t0) * 1000
                n, e = result.nodes_created, result.edges_created
                total_nodes += n
                total_edges += e
                if n == 0 and e == 0:
                    ec["skipped"] += 1
                    events_skipped += 1
                else:
                    ec["processed"] += 1
                    ec["nodes"] += n
                    ec["edges"] += e
                    events_processed += 1
                if result.errors:
                    ec["errors"] += len(result.errors)
                    total_errors.extend(result.errors)

                logger.info(
                    "event_handled",
                    event_type=event_type,
                    source_id=source_id,
                    nodes=n,
                    edges=e,
                    errors=len(result.errors),
                    elapsed_ms=round(elapsed_ms, 1),
                )

                if updated_at and self._tracker and source_id and not result.errors:
                    await self._tracker.record_ingestion(event_type, source_id, org_id, updated_at)

            except Exception as exc:
                logger.warning("org_ingest_item_failed", event_type=event_type, label=label, error=str(exc))
                ec["errors"] += 1
                total_errors.append(f"{event_type}/{label}: {str(exc)[:120]}")

        async def _report(current: str):
            if progress_callback:
                await progress_callback(
                    current_event_type=current,
                    events_processed=events_processed,
                    events_skipped=events_skipped,
                    nodes_created=total_nodes,
                    edges_created=total_edges,
                    errors_count=len(total_errors),
                    event_counts=event_counts,
                )

        for req_id, updated_at in discovery["requisition_ids"]:
            await _run("plan_created", SourceRef(requisition_id=req_id), req_id, updated_at)
            await _heartbeat("plan_created")
        await _report("plan_created")

        for cr_id, updated_at in discovery.get("cr_all", []):
            await _run("feedback_completed", SourceRef(candidate_round_id=cr_id), cr_id, updated_at)
            await _heartbeat("feedback_completed")
        await _report("feedback_completed")

        for cand, updated_at in discovery["decision_candidates"]:
            await _run("decision_made", SourceRef(candidate_id=cand["id"], requisition_id=cand.get("requisition_id")), cand["id"], updated_at)
            await _heartbeat("decision_made")
        await _report("decision_made")

        for cr_id, updated_at in discovery.get("cr_with_question_summaries", []):
            await _run("question_summaries_available", SourceRef(candidate_round_id=cr_id), cr_id, updated_at)
            await _heartbeat("question_summaries_available")
        await _report("question_summaries_available")

        for cr_id, updated_at in discovery.get("cr_with_feedback_transcript", []):
            await _run("feedback_debrief_available", SourceRef(candidate_round_id=cr_id), cr_id, updated_at)
            await _heartbeat("feedback_debrief_available")
        await _report("feedback_debrief_available")

        for cr_id, updated_at in discovery.get("cr_with_segments", []):
            await _run("interview_transcript_available", SourceRef(candidate_round_id=cr_id), cr_id, updated_at)
            await _heartbeat("interview_transcript_available")
        await _report("interview_transcript_available")

        for req_id, updated_at in discovery.get("req_with_intake", []):
            await _run("intake_transcript_available", SourceRef(requisition_id=req_id), req_id, updated_at)
            await _heartbeat("intake_transcript_available")
        await _report("intake_transcript_available")

        for req_id, updated_at in discovery.get("req_with_jd", []):
            await _run("jd_available", SourceRef(requisition_id=req_id), req_id, updated_at)
            await _heartbeat("jd_available")
        await _report("jd_available")

        return {
            "org_id": org_id,
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "total_errors": len(total_errors),
            "events": event_counts,
            "errors": total_errors[:50],
            "events_processed": events_processed,
            "events_skipped": events_skipped,
        }

    async def _batched_in_query(self, client: AsyncClient, table: str, select: str, column: str, values: list[str], extra_filter=None) -> list[dict]:
        results = []
        for i in range(0, len(values), BATCH_SIZE):
            batch = values[i:i + BATCH_SIZE]
            q = client.table(table).select(select).in_(column, batch)
            if extra_filter:
                q = extra_filter(q)
            resp = await q.execute()
            results.extend(resp.data or [])
        return results

    async def _round_ids_for_requisitions(self, client: AsyncClient, requisition_ids: list[str]) -> list[str]:
        rows = await self._batched_in_query(
            client, "rounds", "id", "requisition_id", requisition_ids,
            extra_filter=lambda q: q.is_("deleted_at", "null"),
        )
        return [r["id"] for r in rows]
