"""IntakeSessionService — creates session + draft requisition, triggers prefill Lambda."""

from __future__ import annotations

import os
from typing import Optional
from uuid import UUID

import structlog

from app.api.v2.core.exceptions import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.api.v2.schemas.intake import (
    CreateSessionResponse,
    IntakeFormData,
    IntakeSessionResponse,
)
from app.services._supabase_rows import first_row
from app.services.ats_sync.plan_seed import fetch_seed_rounds
from app.services.jobs.invoker import CONTEXT_BUILDER, get_invoker
from intake_core.questions import QUESTIONS_VERSION, snapshot_questions

logger = structlog.get_logger(__name__)


class IntakeSessionService:
    def __init__(self, supabase_client):
        self.supabase = supabase_client

    async def create_session(
        self,
        user_id: UUID,
        org_id: UUID,
        form_data: Optional[IntakeFormData],
        entry_point: Optional[str],
        requisition_id: Optional[UUID] = None,
    ) -> CreateSessionResponse:
        if requisition_id is not None:
            # Complete-intake path: attach a session to an existing requisition
            # (ATS-imported or otherwise awaiting intake/publish). Idempotent —
            # an active session for the role is resumed, not duplicated.
            req_record = await self._load_requisition_for_intake(
                requisition_id, org_id
            )
            existing = await self._active_session_for_requisition(
                requisition_id, org_id
            )
            if existing is not None:
                if str(existing["user_id"]) != str(user_id):
                    raise ConflictError(
                        "INTAKE_IN_PROGRESS",
                        "A teammate already has an intake in progress for this role",
                    )
                return CreateSessionResponse(
                    session_id=UUID(existing["id"]),
                    requisition_id=requisition_id,
                )
            form_data = _form_data_from_requisition(req_record)
        else:
            if form_data is None:
                raise ValidationError(
                    "form_data is required when requisition_id is not provided"
                )
            # Validate the experience range before touching the DB so an invalid
            # range returns a clean 400 instead of a raw 23514 check_violation.
            # A blank max arrives as None (open-ended), which is always valid.
            if (
                form_data.experience_max is not None
                and form_data.experience_max < form_data.experience_min
            ):
                raise ValidationError(
                    "Maximum experience can't be lower than minimum experience."
                )

            # 1) Insert draft requisition — Migration 94 added 'draft' to status CHECK
            req_row = await (
                self.supabase.table("requisitions")
                .insert({
                    "organization_id": str(org_id),
                    "role_title": form_data.role_name,
                    "experience_min_years": form_data.experience_min,
                    "experience_max_years": form_data.experience_max,
                    "role_location": form_data.location,
                    "job_description": form_data.jd_text,
                    "status": "draft",
                    "created_by": str(user_id),
                })
                .execute_async()
            )
            req_record = first_row(req_row)
            if not req_record:
                raise RuntimeError("Requisition insert returned no data")
            requisition_id = UUID(req_record["id"])

        # 2) Insert intake_sessions row with versioned question snapshot
        session_row = await (
            self.supabase.table("intake_sessions")
            .insert({
                "requisition_id": str(requisition_id),
                "user_id": str(user_id),
                "organization_id": str(org_id),
                "status": "created",
                "entry_point": entry_point,
                "form_data": form_data.model_dump(),
                "questions_version": QUESTIONS_VERSION,
                "questions_snapshot": snapshot_questions(),
            })
            .execute_async()
        )
        session_record = first_row(session_row)
        if not session_record:
            raise RuntimeError("Session insert returned no data")
        session_id = UUID(session_record["id"])

        # 3) Fire prefill asynchronously — don't fail session creation if it errors.
        prefill_invoked = False
        # Plan-seeding (spec §8): pass Ashby interview stages as ADDITIVE context so
        # the generated plan mirrors the ATS structure. Best-effort: [] for non-ATS
        # sessions and on any ATS error (fetch_seed_rounds never raises).
        ats_stages = await fetch_seed_rounds(
            self.supabase,
            organization_id=str(org_id),
            requisition_id=str(requisition_id),
        )
        try:
            await get_invoker().invoke(
                CONTEXT_BUILDER,
                payload={
                    "session_id": str(session_id),
                    "include_turns": False,
                    "ats_stages": ats_stages,
                },
            )
            prefill_invoked = True
        except Exception as e:
            # Best-effort: an unconfigured or unreachable context builder must not
            # fail session creation — the cold-start fallback below covers it.
            logger.error(
                "prefill_dispatch_failed",
                session_id=str(session_id),
                error=str(e),
            )

        if not prefill_invoked:
            # Fall back to cold-start: session is immediately usable with empty answers.
            empty_answers = {
                q["id"]: {"text": None, "extraction_confidence": "none", "sources": []}
                for q in snapshot_questions()
            }
            await self.supabase.table("intake_sessions").update({
                "status": "ready",
                "prefilled_answers": empty_answers,
                "current_answers": empty_answers,
            }).eq("id", str(session_id)).execute_async()

        return CreateSessionResponse(session_id=session_id, requisition_id=requisition_id)

    async def _load_requisition_for_intake(
        self, requisition_id: UUID, org_id: UUID
    ) -> dict:
        """Fetch + gate the requisition a complete-intake session attaches to.

        Only pre-publish states qualify: 'intake_pending' (ATS-imported or
        legacy-created) and 'draft' (intake Hub working copy). Published roles
        already have a plan; closed roles must be reopened first.
        """
        result = await (
            self.supabase.table("requisitions")
            .select(
                "id, status, role_title, role_location, experience_min_years,"
                " experience_max_years, job_description, is_system_template"
            )
            .eq("id", str(requisition_id))
            .eq("organization_id", str(org_id))
            .is_null("deleted_at")
            .single()
            .execute_async()
        )
        row = result.data
        if not row or row.get("is_system_template"):
            raise NotFoundError("Role not found")
        status = row.get("status")
        if status == "closed":
            raise ConflictError(
                "REQ_CLOSED", "Reopen the role before completing its intake"
            )
        if status not in ("draft", "intake_pending"):
            raise ConflictError(
                "INTAKE_ALREADY_COMPLETE",
                "This role is already published — its intake is complete",
            )
        return row

    # Session states that still own the requisition's intake. 'published' and
    # 'abandoned' are terminal: a new session may be started after either.
    _ACTIVE_SESSION_STATUSES = frozenset(
        {"created", "prefilling", "ready", "active", "submitted"}
    )

    async def _active_session_for_requisition(
        self, requisition_id: UUID, org_id: UUID
    ) -> Optional[dict]:
        result = await (
            self.supabase.table("intake_sessions")
            .select("id, user_id, status")
            .eq("requisition_id", str(requisition_id))
            .eq("organization_id", str(org_id))
            .order("created_at", desc=True)
            .limit(20)
            .execute_async()
        )
        for row in result.data or []:
            if row.get("status") in self._ACTIVE_SESSION_STATUSES:
                return row
        return None

    async def list_user_sessions(
        self,
        user_id: UUID,
        organization_id: UUID,
    ) -> "ListSessionsResponse":
        """B1.1: List caller's intake sessions from user_conversation_history view.

        Sorted by last_activity_at DESC, capped at 50. RLS on the view inherits
        from intake_sessions, so the explicit eq() filters are defense-in-depth.
        """
        from app.api.v2.schemas.intake import ListSessionsResponse, SessionListItem

        result = await (
            self.supabase.table("user_conversation_history")
            .select("*")
            .eq("user_id", str(user_id))
            .eq("organization_id", str(organization_id))
            .order("last_activity_at", desc=True)
            .limit(50)
            .execute_async()
        )
        rows = result.data or []

        session_ids = [row["conversation_id"] for row in rows]
        requisition_ids = [row["requisition_id"] for row in rows]

        coverage = await self._coverage_by_session(session_ids)
        plan_stats = await self._plan_stats_by_requisition(requisition_ids)

        items = []
        for row in rows:
            cov = coverage.get(row["conversation_id"], {})
            stats = plan_stats.get(row["requisition_id"], {})
            items.append(
                SessionListItem(
                    session_id=UUID(row["conversation_id"]),
                    requisition_id=UUID(row["requisition_id"]),
                    title=row["title"],
                    display_status=row["display_status"],
                    detail_status=row["detail_status"],
                    last_activity_at=row["last_activity_at"],
                    active_modality=row.get("active_modality"),
                    resume_url=row["resume_url"],
                    role_name=row.get("role_name"),
                    exp_min=row.get("exp_min"),
                    exp_max=row.get("exp_max"),
                    location=row.get("location"),
                    covered=cov.get("covered", 0),
                    total=cov.get("total", len(snapshot_questions())),
                    stopped_at=cov.get("stopped_at"),
                    rounds_count=stats.get("rounds_count", 0),
                    total_minutes=stats.get("total_minutes", 0),
                    candidates_count=stats.get("candidates_count", 0),
                )
            )
        return ListSessionsResponse(sessions=items)

    # The statuses that count toward "goals covered" in the pending list.
    _COVERED_STATUSES = frozenset({"validated", "discussed"})

    async def _coverage_by_session(self, session_ids: list[str]) -> dict[str, dict]:
        """Batch-compute goal coverage from current_answers + questions_snapshot.

        Returns {session_id: {covered, total, stopped_at}}. stopped_at is the
        topic the recruiter is mid-way through (a `needs_probe` answer) or, failing
        that, the first untouched topic — i.e. "where they left off".
        """
        if not session_ids:
            return {}
        result = await (
            self.supabase.table("intake_sessions")
            .select("id,current_answers,questions_snapshot")
            .in_("id", session_ids)
            .execute_async()
        )
        out: dict[str, dict] = {}
        for row in result.data or []:
            snapshot = row.get("questions_snapshot") or snapshot_questions()
            answers = row.get("current_answers") or {}
            topic_by_id = {q["id"]: q.get("topic", q["id"]) for q in snapshot}

            covered = 0
            stopped_at: Optional[str] = None
            first_untouched: Optional[str] = None
            for q in snapshot:
                status = (answers.get(q["id"]) or {}).get("status", "untouched")
                if status in self._COVERED_STATUSES:
                    covered += 1
                elif status == "needs_probe" and stopped_at is None:
                    stopped_at = topic_by_id.get(q["id"])
                elif status in ("untouched", None) and first_untouched is None:
                    first_untouched = topic_by_id.get(q["id"])

            out[row["id"]] = {
                "covered": covered,
                "total": len(snapshot),
                "stopped_at": stopped_at or first_untouched,
            }
        return out

    async def _plan_stats_by_requisition(self, requisition_ids: list[str]) -> dict[str, dict]:
        """Batch-compute rounds count + total duration + candidate count per requisition."""
        if not requisition_ids:
            return {}
        stats: dict[str, dict] = {
            rid: {"rounds_count": 0, "total_minutes": 0, "candidates_count": 0}
            for rid in requisition_ids
        }

        rounds = await (
            self.supabase.table("rounds")
            .select("requisition_id,duration_minutes")
            .in_("requisition_id", requisition_ids)
            .execute_async()
        )
        for r in rounds.data or []:
            rid = r["requisition_id"]
            if rid in stats:
                stats[rid]["rounds_count"] += 1
                stats[rid]["total_minutes"] += r.get("duration_minutes") or 0

        candidates = await (
            self.supabase.table("candidates")
            .select("requisition_id")
            .in_("requisition_id", requisition_ids)
            .is_("deleted_at", "null")
            .execute_async()
        )
        for c in candidates.data or []:
            rid = c["requisition_id"]
            if rid in stats:
                stats[rid]["candidates_count"] += 1

        return stats

    async def get_session(
        self,
        session_id: UUID,
        user_id: UUID,
        organization_id: UUID,
    ) -> IntakeSessionResponse:
        result = await (
            self.supabase.table("intake_sessions")
            .select("*")
            .eq("id", str(session_id))
            .eq("user_id", str(user_id))
            .eq("organization_id", str(organization_id))
            .single()
            .execute_async()
        )
        if not result.data:
            raise LookupError(f"Session {session_id} not found")
        return IntakeSessionResponse(**result.data)


def _form_data_from_requisition(req: dict) -> IntakeFormData:
    """Seed the session form from an existing requisition row, clamping to
    IntakeFormData's bounds so imported (ATS) values can't fail validation."""

    def _clamp_years(value) -> Optional[int]:
        try:
            years = int(value)
        except (TypeError, ValueError):
            return None
        return max(0, min(years, 50))

    exp_min = _clamp_years(req.get("experience_min_years")) or 0
    exp_max = _clamp_years(req.get("experience_max_years"))
    if exp_max is not None and exp_max < exp_min:
        exp_max = None
    jd = (req.get("job_description") or "").strip()
    return IntakeFormData(
        role_name=((req.get("role_title") or "").strip() or "Imported role")[:200],
        experience_min=exp_min,
        experience_max=exp_max,
        location=((req.get("role_location") or "").strip() or "Not specified")[:200],
        jd_text=jd[:50_000] if jd else None,
    )
