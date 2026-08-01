"""
Role (requisition) header read + open/close lifecycle.

Endpoints owned:
  GET   /roles              → list_roles (paginated, with status_counts + per-row pipeline)
  GET   /roles/{id}         → get_role_header
  POST  /roles/{id}/close   → close_role
  POST  /roles/{id}/reopen  → reopen_role
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from app.api.v2.core.exceptions import NotFoundError
from app.api.v2.schemas.role import (
    RoleHeaderCounts,
    RoleHeaderResponse,
    RolePipelineCounts,
    RolesListResponse,
    RoleStatusCounts,
)


# Canonical → UI status alias map used in the LIST response's status_counts.
# ATS-imported reqs land directly at intake_pending (migration 127), so the
# Pending tab is a plain status match. 'draft' stays the intake Hub's internal
# pre-submit state (native source) and never surfaces in the roles rail.
_UI_STATUS_BY_CANONICAL = {
    "planned": "open",
    "intake_pending": "pending",
    "closed": "closed",
}

# Reverse map (UI → canonical) is not needed today because the LIST filter
# accepts canonical status directly; FE maps tab keys before sending.


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _compute_days_open(created_at_value: Any) -> int:
    if created_at_value is None:
        return 0
    if isinstance(created_at_value, datetime):
        dt = created_at_value
    else:
        try:
            dt = datetime.fromisoformat(str(created_at_value).replace("Z", "+00:00"))
        except Exception:
            return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    return max(delta.days, 0)


def _extract_created_by_name(req_row: dict) -> Optional[str]:
    """Pull `full_name` out of the embedded select, tolerating both the
    aliased relationship key (`created_by_profile`) and the bare `profiles`
    fallback PostgREST may emit."""
    for key in ("created_by_profile", "profiles"):
        joined = req_row.get(key)
        if isinstance(joined, dict):
            return joined.get("full_name")
        if isinstance(joined, list) and joined and isinstance(joined[0], dict):
            return joined[0].get("full_name")
    return None


def _row_to_role_header(
    req: dict,
    *,
    pipeline: Optional[RolePipelineCounts] = None,
) -> RoleHeaderResponse:
    """Shared shape builder used by list_roles + get_role_header.

    `pipeline` is the per-row pipeline summary (round_count, candidate_count)
    when called from list_roles. detail-mode callers leave it None — the
    detail page reads `counts` instead.
    """
    return RoleHeaderResponse(
        id=UUID(req["id"]),
        role_title=req.get("role_title") or "",
        role_location=req.get("role_location"),
        department=None,
        status=req.get("status") or "",
        created_by=UUID(req["created_by"]) if req.get("created_by") else None,
        created_by_name=_extract_created_by_name(req),
        experience_min_years=req.get("experience_min_years"),
        experience_max_years=req.get("experience_max_years"),
        must_have_skills=req.get("must_have_skills") or [],
        good_to_have_skills=req.get("good_to_have_skills") or [],
        job_description=req.get("job_description"),
        intake_notes=req.get("intake_notes"),
        created_at=req["created_at"],
        days_open=_compute_days_open(req.get("created_at")),
        source=req.get("source") or "native",
        ats_provider=req.get("ats_provider"),
        counts=RoleHeaderCounts(
            candidates_total=0,
            candidates_active=0,
            candidates_hired=0,
            candidates_rejected=0,
            rounds_total=0,
        ),
        pipeline=pipeline or RolePipelineCounts(),
    )


# ---------------------------------------------------------------------------
# GET /roles  (list, paginated)
# ---------------------------------------------------------------------------


async def list_roles(
    supabase,
    org_id: str,
    *,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 10,
    q: Optional[str] = None,
) -> RolesListResponse:
    """Paginated roles list for the rail view.

    Contract (per the design image attached to the role-list ticket):
      Response: { items, page, page_size, total, status_counts }
      - `total` is the size of the filtered (by status, if provided) set.
      - `status_counts` is org-wide (independent of the status filter) so
        the FE can render tab badges from a single response.
      - Each item carries `pipeline: { round_count, candidate_count }` —
        eliminates the N+1 useCandidatesForRequisition fetch the FE used
        to do per row.

    `status` is the **canonical** requisition status (`planned`,
    `intake_pending`, `closed`), per spec §15: "Enum: 'intake_pending' |
    'planned' | 'closed'. No 'pending' / 'open' / 'archived' — those were
    UI inventions." UI maps its tab labels (Open/Pending/Closed) to
    canonical status before calling.

    No embedded profiles join — see commit history: PostgREST silently
    returns no rows when the FK disambiguation syntax doesn't resolve.
    """
    page = max(page, 1)
    page_size = max(min(page_size, 100), 1)
    offset = (page - 1) * page_size

    # `is_system_template=true` rows are the org's materialized
    # generic-untracked-interview requisition (see v1
    # untracked_capture_service.py:258). They surface through the
    # /untracked-interviews tab, not the regular Open/Pending/Closed tabs,
    # so we exclude them here to match v1 list_requisitions behavior.
    def _apply_list_filters(qb):
        qb = (
            qb.eq("organization_id", org_id)
            .is_null("deleted_at")
            .is_("is_system_template", "false")
        )
        if status is not None:
            qb = qb.eq("status", status)
        # Global search across all pages, server-side. Filters by role_title
        # or role_location (case-insensitive substring). status_counts on
        # the response stays org-wide so tab badges don't change while typing.
        if q is not None and q.strip():
            # Escape PostgREST's `or` separator (commas, parens) before
            # splicing into the or-filter string. The custom client's method is
            # `or_filter` (it sets the PostgREST `or=(...)` param); calling the
            # non-existent `.or_()` raised AttributeError and 500'd every search.
            needle = (
                q.strip()
                .replace("%", r"\%")
                .replace(",", r"\,")
                .replace("(", r"\(")
                .replace(")", r"\)")
            )
            pattern = f"*{needle}*"
            qb = qb.or_filter(
                f"role_title.ilike.{pattern},role_location.ilike.{pattern}"
            )
        return qb

    # Stage 1 (3-way parallel): page count, page slice, org-wide status_counts.
    # Each query gets its own builder instance — the fluent builders mutate
    # `self`, so sharing a base would race when run via asyncio.gather.
    count_query = _apply_list_filters(supabase.table("requisitions").select("*"))
    slice_query = (
        _apply_list_filters(supabase.table("requisitions").select("*"))
        .order("created_at", desc=True)
        .limit(page_size)
        .offset(offset)
    )
    status_query = (
        supabase.table("requisitions")
        .select("status")
        .eq("organization_id", org_id)
        .is_null("deleted_at")
        .is_("is_system_template", "false")
    )
    total, slice_result, status_rows_result = await asyncio.gather(
        count_query.count_async(),
        slice_query.execute_async(),
        status_query.execute_async(),
    )
    rows = slice_result.data or []

    # Stage 2 (2-way parallel): per-row pipeline counts. Both queries are
    # keyed on the page's req_ids only, so they're independent.
    req_ids = [str(r["id"]) for r in rows if r.get("id")]
    pipeline_by_req: dict[str, RolePipelineCounts] = {}
    if req_ids:
        rounds_rows, cand_rows = await asyncio.gather(
            supabase.table("rounds")
            .select("id, requisition_id")
            .in_("requisition_id", req_ids)
            .is_null("for_candidate_id")
            .is_null("removed_from_plan_at")
            .is_null("deleted_at")
            .execute_async(),
            supabase.table("candidates")
            .select("id, requisition_id")
            .in_("requisition_id", req_ids)
            .is_null("deleted_at")
            .execute_async(),
        )
        round_count_by_req: dict[str, int] = {}
        for r in rounds_rows.data or []:
            key = str(r.get("requisition_id") or "")
            if key:
                round_count_by_req[key] = round_count_by_req.get(key, 0) + 1
        cand_count_by_req: dict[str, int] = {}
        for c in cand_rows.data or []:
            key = str(c.get("requisition_id") or "")
            if key:
                cand_count_by_req[key] = cand_count_by_req.get(key, 0) + 1
        for rid in req_ids:
            pipeline_by_req[rid] = RolePipelineCounts(
                round_count=round_count_by_req.get(rid, 0),
                candidate_count=cand_count_by_req.get(rid, 0),
            )

    items = [
        _row_to_role_header(r, pipeline=pipeline_by_req.get(str(r["id"])))
        for r in rows
    ]

    bucket = {"open": 0, "pending": 0, "closed": 0}
    for row in status_rows_result.data or []:
        ui = _UI_STATUS_BY_CANONICAL.get(str(row.get("status") or ""))
        if ui:
            bucket[ui] += 1
    status_counts = RoleStatusCounts(**bucket)

    return RolesListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        status_counts=status_counts,
    )


# ---------------------------------------------------------------------------
# GET /roles/{id}
# ---------------------------------------------------------------------------


async def get_role_header(
    supabase, org_id: str, role_id: UUID
) -> RoleHeaderResponse:
    # No embedded profiles join: PostgREST's `profiles!created_by(...)` syntax
    # silently returns no rows here (FK is named `requisitions_created_by_fkey`,
    # not `created_by`). Fetch the role row, then look up the creator's name
    # separately if there is one.
    req_result = await (
        supabase.table("requisitions")
        .select("*")
        .eq("id", str(role_id))
        .eq("organization_id", org_id)
        .is_null("deleted_at")
        .is_("is_system_template", "false")
        .single()
        .execute_async()
    )

    if not req_result.data:
        raise NotFoundError("Role not found")

    req = req_result.data

    # Three independent reads. Run them in parallel:
    #   - creator full_name (best-effort, only when created_by is set)
    #   - candidates status set (for the per-status counts)
    #   - rounds (for rounds_total)
    # The custom Supabase client exposes .single() but not .maybe_single(),
    # and .single() raises when the row is missing — so the creator lookup
    # uses .limit(1).execute_async() instead.
    candidates_query = (
        supabase.table("candidates")
        .select("status")
        .eq("requisition_id", str(role_id))
        .is_null("deleted_at")
    )
    rounds_query = (
        supabase.table("rounds")
        .select("id")
        .eq("requisition_id", str(role_id))
        .is_null("for_candidate_id")
        .is_null("removed_from_plan_at")
        .is_null("deleted_at")
    )

    async def _fetch_creator():
        if not req.get("created_by"):
            return None
        return await (
            supabase.table("profiles")
            .select("full_name")
            .eq("id", req["created_by"])
            .limit(1)
            .execute_async()
        )

    creator_result, candidates_result, rounds_result = await asyncio.gather(
        _fetch_creator(),
        candidates_query.execute_async(),
        rounds_query.execute_async(),
    )

    if creator_result is not None:
        creator_rows = creator_result.data or []
        if creator_rows and isinstance(creator_rows[0], dict):
            req["created_by_profile"] = {"full_name": creator_rows[0].get("full_name")}

    cand_rows = candidates_result.data or []
    candidates_total = len(cand_rows)
    candidates_active = sum(1 for c in cand_rows if c.get("status") == "active")
    candidates_hired = sum(1 for c in cand_rows if c.get("status") == "hired")
    candidates_rejected = sum(1 for c in cand_rows if c.get("status") == "rejected")

    rounds_total = len(rounds_result.data or [])

    return RoleHeaderResponse(
        id=UUID(req["id"]),
        role_title=req.get("role_title") or "",
        role_location=req.get("role_location"),
        # Spec §15: `department` has no DB column yet — return null.
        department=None,
        status=req.get("status") or "",
        created_by=UUID(req["created_by"]) if req.get("created_by") else None,
        created_by_name=_extract_created_by_name(req),
        experience_min_years=req.get("experience_min_years"),
        experience_max_years=req.get("experience_max_years"),
        must_have_skills=req.get("must_have_skills") or [],
        good_to_have_skills=req.get("good_to_have_skills") or [],
        job_description=req.get("job_description"),
        intake_notes=req.get("intake_notes"),
        created_at=req["created_at"],
        days_open=_compute_days_open(req.get("created_at")),
        source=req.get("source") or "native",
        ats_provider=req.get("ats_provider"),
        counts=RoleHeaderCounts(
            candidates_total=candidates_total,
            candidates_active=candidates_active,
            candidates_hired=candidates_hired,
            candidates_rejected=candidates_rejected,
            rounds_total=rounds_total,
        ),
        # Mirror pipeline so consumers that read either field get the same
        # data; the detail page itself reads `counts`.
        pipeline=RolePipelineCounts(
            round_count=rounds_total,
            candidate_count=candidates_total,
        ),
    )


# ---------------------------------------------------------------------------
# POST /roles/{id}/close
# ---------------------------------------------------------------------------


async def _fetch_role_row_for_org(
    supabase, role_id: UUID, org_id: str
) -> Optional[dict]:
    # System-template requisitions (untracked-generic) are excluded so
    # /roles/{id}/close and /reopen can't mutate them.
    result = await (
        supabase.table("requisitions")
        .select("*")
        .eq("id", str(role_id))
        .eq("organization_id", org_id)
        .is_null("deleted_at")
        .is_("is_system_template", "false")
        .single()
        .execute_async()
    )
    return result.data or None


async def close_role(supabase, org_id: str, role_id: UUID) -> dict:
    """Idempotent close. Spec §8.2 row 10: no cascade — scheduled rounds
    proceed unless individually cancelled."""
    now = datetime.now(timezone.utc).isoformat()
    update_result = await (
        supabase.table("requisitions")
        .update({"status": "closed", "updated_at": now})
        .eq("id", str(role_id))
        .eq("organization_id", org_id)
        .neq("status", "closed")
        .is_("deleted_at", "null")
        .is_("is_system_template", "false")
        .execute_async()
    )
    if update_result.data:
        return update_result.data

    current = await _fetch_role_row_for_org(supabase, role_id, org_id)
    if current is None:
        raise NotFoundError("Role not found")
    return current


async def reopen_role(supabase, org_id: str, role_id: UUID) -> dict:
    """Reopen a closed requisition by transitioning back to 'planned'."""
    now = datetime.now(timezone.utc).isoformat()
    update_result = await (
        supabase.table("requisitions")
        .update({"status": "planned", "updated_at": now})
        .eq("id", str(role_id))
        .eq("organization_id", org_id)
        .eq("status", "closed")
        .is_("deleted_at", "null")
        .is_("is_system_template", "false")
        .execute_async()
    )
    if update_result.data:
        return update_result.data

    current = await _fetch_role_row_for_org(supabase, role_id, org_id)
    if current is None:
        raise NotFoundError("Role not found")
    return current
