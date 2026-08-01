from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import structlog
from postgrest.exceptions import APIError

logger = structlog.get_logger(__name__)

TABLE = "cortex_org_ingest_jobs"
# Org ingest runs can have minutes-long per-item LLM/Neo4j latency (e.g.
# interview_transcript_available with hundreds of triplets). A real heartbeat
# fires from inside OrgIngestionService every few seconds, so this threshold
# only kicks in when the worker is genuinely dead. 15 min comfortably covers
# worst-case per-item stalls (network blips, Aura cold starts, OpenAI 429s)
# without making restart recovery painfully slow.
STALE_RUNNING_THRESHOLD_MINUTES = 15
UNIQUE_VIOLATION_PG_CODE = "23505"


class OrgIngestJobService:
    """CRUD + lifecycle for cortex_org_ingest_jobs rows.

    Mirrors ForcePublishJobService (migration 74/75) for the end-to-end
    POST /ingest/org/async path. Different columns because org-ingest needs
    per-event-type progress, accumulating node/edge counters, and the
    currently-processing event_type for visibility while a long run is
    in flight.

    Stale recovery: a row whose `updated_at` hasn't moved in
    STALE_RUNNING_THRESHOLD_MINUTES is marked failed before allowing a
    new job — restarts auto-recover without admin intervention.
    """

    def __init__(self, supabase: Any):
        self._supabase = supabase

    async def _recover_stale_running(self, org_id: str) -> None:
        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(minutes=STALE_RUNNING_THRESHOLD_MINUTES)
        ).isoformat()
        await (
            self._supabase.table(TABLE)
            .update({
                "status": "failed",
                "error_message": f"Job marked stale: no progress for >{STALE_RUNNING_THRESHOLD_MINUTES} minutes (likely container restart)",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("org_id", org_id)
            .in_("status", ["pending", "running"])
            .lt("updated_at", cutoff)
            .execute()
        )

    async def find_active(self, org_id: str) -> dict | None:
        resp = await (
            self._supabase.table(TABLE)
            .select("id, status, events_processed, events_total, started_at, updated_at")
            .eq("org_id", org_id)
            .in_("status", ["pending", "running"])
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None

    async def create_or_409(self, org_id: str) -> tuple[str, bool]:
        """Returns (job_id, created). See ForcePublishJobService.create_or_409
        for race semantics — same partial-unique-index pattern."""
        await self._recover_stale_running(org_id)

        job_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        try:
            await (
                self._supabase.table(TABLE)
                .insert({
                    "id": job_id,
                    "org_id": org_id,
                    "status": "pending",
                    "events_total": 0,
                    "events_processed": 0,
                    "events_skipped": 0,
                    "nodes_created": 0,
                    "edges_created": 0,
                    "errors_count": 0,
                    "event_counts": {},
                    "errors": [],
                    "started_at": now,
                    "updated_at": now,
                })
                .execute()
            )
            return job_id, True
        except APIError as e:
            if getattr(e, "code", None) != UNIQUE_VIOLATION_PG_CODE:
                raise
            existing = await self.find_active(org_id)
            if existing is None:
                raise
            return str(existing["id"]), False

    async def mark_running(self, job_id: str, events_total: int) -> None:
        await (
            self._supabase.table(TABLE)
            .update({
                "status": "running",
                "events_total": events_total,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", job_id)
            .execute()
        )

    async def update_progress(
        self,
        job_id: str,
        *,
        current_event_type: str | None,
        events_processed: int,
        events_skipped: int,
        nodes_created: int,
        edges_created: int,
        errors_count: int,
        event_counts: dict,
    ) -> None:
        await (
            self._supabase.table(TABLE)
            .update({
                "current_event_type": current_event_type,
                "events_processed": events_processed,
                "events_skipped": events_skipped,
                "nodes_created": nodes_created,
                "edges_created": edges_created,
                "errors_count": errors_count,
                "event_counts": event_counts,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", job_id)
            .execute()
        )

    async def mark_completed(
        self,
        job_id: str,
        *,
        events_processed: int,
        events_skipped: int,
        nodes_created: int,
        edges_created: int,
        errors_count: int,
        event_counts: dict,
        errors: list[str],
    ) -> None:
        await self._mark_terminal(
            job_id,
            status="completed",
            events_processed=events_processed,
            events_skipped=events_skipped,
            nodes_created=nodes_created,
            edges_created=edges_created,
            errors_count=errors_count,
            event_counts=event_counts,
            errors=errors,
        )

    async def mark_partial(
        self,
        job_id: str,
        *,
        events_processed: int,
        events_skipped: int,
        nodes_created: int,
        edges_created: int,
        errors_count: int,
        event_counts: dict,
        errors: list[str],
    ) -> None:
        """Some events processed cleanly, some errored. Distinct from `failed`
        (zero nodes+edges produced) so callers can tell a degraded run from
        a total outage."""
        await self._mark_terminal(
            job_id,
            status="partial",
            events_processed=events_processed,
            events_skipped=events_skipped,
            nodes_created=nodes_created,
            edges_created=edges_created,
            errors_count=errors_count,
            event_counts=event_counts,
            errors=errors,
        )

    async def _mark_terminal(
        self,
        job_id: str,
        *,
        status: str,
        events_processed: int,
        events_skipped: int,
        nodes_created: int,
        edges_created: int,
        errors_count: int,
        event_counts: dict,
        errors: list[str],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await (
            self._supabase.table(TABLE)
            .update({
                "status": status,
                "current_event_type": None,
                "events_processed": events_processed,
                "events_skipped": events_skipped,
                "nodes_created": nodes_created,
                "edges_created": edges_created,
                "errors_count": errors_count,
                "event_counts": event_counts,
                "errors": errors,
                "updated_at": now,
                "completed_at": now,
            })
            .eq("id", job_id)
            .execute()
        )

    async def mark_failed(self, job_id: str, error_message: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await (
            self._supabase.table(TABLE)
            .update({
                "status": "failed",
                "error_message": error_message[:500],
                "updated_at": now,
                "completed_at": now,
            })
            .eq("id", job_id)
            .execute()
        )

    async def get(self, job_id: str) -> dict | None:
        resp = await (
            self._supabase.table(TABLE)
            .select("*")
            .eq("id", job_id)
            .maybe_single()
            .execute()
        )
        if not resp or not resp.data:
            return None
        return resp.data
