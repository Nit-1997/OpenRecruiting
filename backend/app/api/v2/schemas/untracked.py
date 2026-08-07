"""Untracked-interview response schemas (v2, read-only).

The role-detail v2 spec doesn't cover untracked interviews — they are a
separate concern — but the v2 frontend must not call v1 endpoints (two API base URLs, two CORS setups, two auth flows). This
schema lives under v2 so the FE keeps a single `/api/v2/*` base.

Shape mirrors the v2 frontend `UntrackedInterview` domain type
(`recruiter-app-v2/src/domain/untracked.ts`) so the FE service layer is a
pure passthrough.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr


class UntrackedInterviewResponse(BaseModel):
    """One untracked interview, shaped for the v2 FE."""

    # `id` here is the source candidate_round id — that's the durable
    # identifier the FE keys against. (v1 calls it
    # source_candidate_round_id; v2 collapses it to `id` for the FE.)
    id: UUID
    candidate_name: str
    candidate_email: str
    event_title: str
    # ISO 8601 string; FE renders via `new Date(event_start)`.
    event_start: datetime
    # Source detection rows don't carry duration today; surface 0 when
    # missing so the FE type (number) stays satisfied.
    event_duration_minutes: int = 0
    interviewer_email: str
    recording_url: Optional[str] = None
    status: str  # 'available' | 'imported' | 'dismissed' — matches FE UntrackedStatus
    imported_candidate_id: Optional[UUID] = None
    imported_requisition_id: Optional[UUID] = None
    # Source-side identity for the captured candidate + their org's
    # generic (materialized) requisition. The FE uses these to open the
    # existing `GET /roles/{id}/candidates/{cid}/packet` endpoint for
    # the captured generic round — so the standard PacketDrawer renders
    # the feedback packet without a special-case route.
    source_candidate_id: UUID
    source_requisition_id: UUID
    # Use event_start as a stand-in for detection time; v1 doesn't expose
    # a dedicated detected_at on the list either.
    detected_at: datetime


class UntrackedInterviewListResponse(BaseModel):
    """Paginated wrapper for GET /untracked-interviews.

    The roles-list design (image attached on the role-list ticket) calls
    out untracked interviews as a separate API surface with its own
    pagination — distinct from the roles list — so the FE Untracked tab
    can load page 2 without refetching active roles.
    """

    items: list[UntrackedInterviewResponse]
    page: int
    page_size: int
    total: int


class LinkToExistingRequest(BaseModel):
    """Body for POST /untracked-interviews/{id}/link-to-existing.

    Two product flows, controlled by `mode`:
      - 'new_candidate'   : create a fresh candidate in target_requisition.
                            target_candidate_id must NOT be set.
      - 'merge_existing'  : attach this interview to an already-existing
                            candidate (target_candidate_id) in the role.
    target_round_id is optional — if omitted the service picks the
    target requisition's first active shared round.
    """

    requisition_id: UUID
    mode: str = "new_candidate"  # 'new_candidate' | 'merge_existing'
    target_candidate_id: Optional[UUID] = None
    target_round_id: Optional[UUID] = None
    # Interviewer + date attached to the target round on associate. The
    # interviewer drives the "Send feedback request" path (the real scorecard);
    # scheduled_at overrides the date copied from the source interview.
    interviewer_email: Optional[EmailStr] = None
    interviewer_name: Optional[str] = None
    scheduled_at: Optional[datetime] = None


class LinkToExistingResponse(BaseModel):
    """Returned after a successful link-to-existing import."""

    untracked_id: UUID
    target_requisition_id: UUID
    target_round_id: UUID
    target_candidate_id: UUID
    target_candidate_round_id: UUID
    candidate_created: bool


class MarkNotInterviewResponse(BaseModel):
    """Returned after marking an untracked row as 'not an interview'."""

    untracked_id: UUID
    status: str  # always 'dismissed'


class UndoLinkResponse(BaseModel):
    """Returned after undoing an untracked-interview association."""

    untracked_id: UUID
    target_candidate_round_id: Optional[UUID] = None
    restored_prior_scorecard: bool = False
