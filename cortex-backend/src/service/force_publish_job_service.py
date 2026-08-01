from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import structlog
from postgrest.exceptions import APIError

logger = structlog.get_logger(__name__)

TABLE = "cortex_force_publish_jobs"
STALE_RUNNING_THRESHOLD_MINUTES = 5
UNIQUE_VIOLATION_PG_CODE = "23505"


class ForcePublishJobService:
    """CRUD + lifecycle for cortex_force_publish_jobs rows.

    The async force-publish workflow:
      1. Caller asks `create_or_409(org_id)` → returns either a fresh job_id or
         the id of an in-flight job for the same org (caller maps to HTTP 409).
      2. The spawned task reports per-batch progress via `update_progress`.
      3. On exit, the task calls `mark_completed` or `mark_failed`.

    Stale recovery: a `running` row whose `updated_at` hasn't moved in
    STALE_RUNNING_THRESHOLD_MINUTES means the container that spawned it died.
    `create_or_409` marks those failed before deciding whether to allow a new
    job — restarts auto-recover with no admin intervention.
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
            .select("id, status, scanned, published, batches, started_at, updated_at")
            .eq("org_id", org_id)
            .in_("status", ["pending", "running"])
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None

    async def create_or_409(self, org_id: str) -> tuple[str, bool]:
        """Returns (job_id, created).

        created=True  → fresh job, caller should spawn the task.
        created=False → an active job already exists for this org; job_id is
                        the existing one, caller should return 409.

        Race-free at the DB boundary: the partial unique index
        `cortex_force_publish_jobs_one_active_per_org` (migration 75) makes the
        INSERT fail with Postgres 23505 if another pending/running row already
        exists for this org. We catch the violation and resolve the race by
        fetching the row that won. A prior check-then-insert version allowed
        two concurrent POSTs to both pass the `find_active` check and both
        insert — defeating the at-most-one-active guarantee.
        """
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
                    "scanned": 0,
                    "published": 0,
                    "batches": 0,
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
                # Index said an active row exists, but the lookup can't find it.
                # Could happen if the winning task transitioned out of
                # (pending|running) between the conflict and our re-fetch.
                # Re-raise so the caller surfaces an honest error instead of
                # silently dropping the request.
                raise
            return str(existing["id"]), False

    async def mark_running(self, job_id: str) -> None:
        await (
            self._supabase.table(TABLE)
            .update({
                "status": "running",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", job_id)
            .execute()
        )

    async def update_progress(
        self,
        job_id: str,
        *,
        scanned: int,
        published: int,
        batches: int,
    ) -> None:
        await (
            self._supabase.table(TABLE)
            .update({
                "scanned": scanned,
                "published": published,
                "batches": batches,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", job_id)
            .execute()
        )

    async def mark_completed(
        self,
        job_id: str,
        *,
        scanned: int,
        published: int,
        batches: int,
        errors: list[str],
    ) -> None:
        await self._mark_terminal(
            job_id,
            status="completed",
            scanned=scanned,
            published=published,
            batches=batches,
            errors=errors,
        )

    async def mark_partial(
        self,
        job_id: str,
        *,
        scanned: int,
        published: int,
        batches: int,
        errors: list[str],
    ) -> None:
        """Some rows published, some failed. Distinct from `failed` (zero
        published) so operators polling status can tell a degraded run from a
        total outage."""
        await self._mark_terminal(
            job_id,
            status="partial",
            scanned=scanned,
            published=published,
            batches=batches,
            errors=errors,
        )

    async def _mark_terminal(
        self,
        job_id: str,
        *,
        status: str,
        scanned: int,
        published: int,
        batches: int,
        errors: list[str],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await (
            self._supabase.table(TABLE)
            .update({
                "status": status,
                "scanned": scanned,
                "published": published,
                "batches": batches,
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
