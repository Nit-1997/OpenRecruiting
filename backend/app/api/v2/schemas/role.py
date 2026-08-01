"""Role-header (requisition) response schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class RoleHeaderCounts(BaseModel):
    candidates_total: int
    candidates_active: int
    candidates_hired: int
    candidates_rejected: int
    rounds_total: int


class RolePipelineCounts(BaseModel):
    """Per-row pipeline summary surfaced in the roles LIST response so the UI
    can render `N candidates · M rounds` without an N+1 fetch per row.

    `round_count` = active shared rounds for the requisition (excludes
    soft-deleted, removed-from-plan, and per-candidate custom rounds).
    `candidate_count` = non-deleted candidates on the requisition (any
    status). UI may further bucket by status via the role-detail page if
    finer granularity is required.
    """

    round_count: int = 0
    candidate_count: int = 0


class RoleHeaderResponse(BaseModel):
    id: UUID
    role_title: str
    role_location: Optional[str] = None
    department: Optional[str] = None
    status: str
    created_by: Optional[UUID] = None
    created_by_name: Optional[str] = None
    experience_min_years: Optional[int] = None
    experience_max_years: Optional[int] = None
    must_have_skills: list[str] = []
    good_to_have_skills: list[str] = []
    job_description: Optional[str] = None
    intake_notes: Optional[str] = None
    created_at: datetime
    days_open: int
    # Provenance (phase-2 ATS import): 'native' | 'ats_sync', plus the ATS the
    # requisition was imported from (e.g. 'workable') — drives the FE badge.
    source: str = "native"
    ats_provider: Optional[str] = None
    counts: RoleHeaderCounts
    # Populated in LIST mode (GET /roles). Always present so the FE doesn't
    # have to branch on shape; populated with zeros in detail mode where the
    # role-detail page consumes `counts` instead.
    pipeline: RolePipelineCounts = RolePipelineCounts()


class RoleStatusCounts(BaseModel):
    """Status-bucketed totals across the caller's org. Computed once per
    `GET /roles` call so the FE tab badges stay in sync with the paginated
    item windows.

    Keys are UI-friendly aliases mapped from canonical statuses:
        open    ← requisitions.status = 'planned'
        pending ← requisitions.status = 'intake_pending'
        closed  ← requisitions.status = 'closed'
    """

    open: int = 0
    pending: int = 0
    closed: int = 0


class RolesListResponse(BaseModel):
    """Wrapper for GET /roles.

    `items` is the requested page; `total` reflects the filtered set (after
    `status` is applied); `status_counts` is the org-wide breakdown. The FE
    page-mount pattern (spec image at docs/superpowers/specs/
    2026-05-18-roles-detail-v2-api-design.md image attached) fires three
    parallel requests with status=open|pending|closed; status_counts on each
    response is identical and any one is sufficient for tab badges.
    """

    items: list[RoleHeaderResponse]
    page: int
    page_size: int
    total: int
    status_counts: RoleStatusCounts
