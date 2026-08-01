"""IntakeSubmitService — flips session to 'submitted' and invokes the v2 scorecard Lambda."""
from __future__ import annotations

import os
from typing import Any
from uuid import UUID

import structlog

from app.services._supabase_rows import now_iso
from app.services.jobs.invoker import INTAKE
from app.services.intake._session_ops import (
    invoke_worker_or_rollback,
    load_owned_session,
    optimistic_flip,
)

logger = structlog.get_logger(__name__)


class IntakeSubmitError(Exception):
    """Raised when a session is not in a valid state to submit."""

    def __init__(self, message: str, status_code: int = 409):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class IntakeSubmitService:
    def __init__(self, supabase_client):
        self.supabase = supabase_client

    async def submit(
        self,
        session_id: UUID,
        user_id: UUID,
        organization_id: UUID,
    ) -> dict[str, Any]:
        # 1) Load session, validate state — scoped to caller's user + org
        row = await load_owned_session(
            self.supabase,
            session_id=session_id,
            user_id=user_id,
            organization_id=organization_id,
            columns="id,status,current_answers,requisition_id",
        )
        if not row:
            raise IntakeSubmitError(f"Session {session_id} not found", status_code=404)

        # Submittable = the prefill is done ('ready') OR the recruiter is mid-conversation
        # ('active'). A text turn flips status to 'active' (text_runner) and never flips it
        # back to 'ready', and voice only returns to 'ready' on a clean [END]; gating on
        # 'ready' alone made any in-progress session permanently un-submittable. The submit
        # modal explicitly offers "submit at N/9, the rest are optional", so 'active' must
        # be accepted. 'created'/'prefilling' are NOT submittable (no answers yet).
        _SUBMITTABLE = ("ready", "active")
        status = row.get("status")
        if status == "published":
            raise IntakeSubmitError("Session already published")
        if status == "submitted":
            raise IntakeSubmitError("Session already submitted (Lambda is running)")
        if status not in _SUBMITTABLE:
            raise IntakeSubmitError(
                f"Cannot submit — intake is still {status}. Wait for prefill to finish.",
                status_code=409,
            )
        if not row.get("current_answers"):
            raise IntakeSubmitError("Cannot submit — no current_answers on session", status_code=400)

        requisition_id = row.get("requisition_id")

        # 2) Atomic flip to 'submitted' — the .in_("status", _SUBMITTABLE) is the race-condition
        # gate: Postgres serializes row-level locks so only ONE concurrent UPDATE will match;
        # the others see zero rows and get the 409 below instead of invoking Lambda twice.
        won = await optimistic_flip(
            self.supabase,
            session_id=session_id,
            user_id=user_id,
            organization_id=organization_id,
            values={
                "status": "submitted",
                "submitted_at": now_iso(),
                "process_status": "running",
                "process_error": None,
            },
            guards=[("in_", "status", list(_SUBMITTABLE))],
        )
        if not won:
            raise IntakeSubmitError(
                "Session is not in a submittable state (already submitted or concurrent request won the race)",
                status_code=409,
            )

        # 2b) Advance requisition draft → intake_pending so it appears in dashboard filters.
        # The .eq("status", "draft") guard is idempotent — won't rollback an already-planned req.
        if requisition_id:
            await self.supabase.table("requisitions").update({
                "status": "intake_pending",
            }).eq("id", str(requisition_id)).eq("organization_id", str(organization_id)).eq("status", "draft").execute_async()

        # 3) Hand the session to the intake worker.
        try:
            await invoke_worker_or_rollback(
                self.supabase,
                session_id=session_id,
                user_id=user_id,
                organization_id=organization_id,
                target=INTAKE,
                payload={"session_id": str(session_id)},
                rollback_values={
                    "status": "ready",
                    "process_status": "failed",
                    "process_error": "Worker dispatch failed",
                },
            )
        except Exception as e:
            logger.error("submit_job_dispatch_failed", session_id=str(session_id), error=str(e))
            raise IntakeSubmitError(f"Failed to start intake processing: {e}", status_code=500)

        return {"session_id": str(session_id), "status": "submitted"}
