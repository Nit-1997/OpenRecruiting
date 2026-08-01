"""
Untracked-interview routes (v2).

  GET  /untracked-interviews                              — paginated list
  POST /untracked-interviews/{id}/link-to-existing        — link into a role
  POST /untracked-interviews/{id}/mark-not-interview      — dismiss as not-an-interview

The role-detail v2 spec doesn't cover untracked-interview mutations, but
the FE roles rail surfaces a 3-button control (Import as a New Role / Link
to Existing / Not an Interview). "Import as a New Role" is FE-only routing
into the intake flow; the other two are backend mutations exposed here.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.api.v2.schemas.untracked import (
    LinkToExistingRequest,
    LinkToExistingResponse,
    MarkNotInterviewResponse,
    UndoLinkResponse,
    UntrackedInterviewListResponse,
    UntrackedInterviewResponse,
)
from app.api.v2.services import untracked_service
from app.api.v2.services.untracked_service import UntrackedMutationError


router = APIRouter(tags=["v2/untracked"])


@router.get(
    "/untracked-interviews",
    response_model=UntrackedInterviewListResponse,
)
async def list_untracked_interviews(
    page: int = Query(1, ge=1, description="1-indexed page number."),
    page_size: int = Query(
        10, ge=1, le=100, description="Page size. Default 10, max 100."
    ),
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> UntrackedInterviewListResponse:
    rows, total = await untracked_service.list_untracked(
        supabase,
        current.organization_id_str,
        page=page,
        page_size=page_size,
    )
    return UntrackedInterviewListResponse(
        items=[UntrackedInterviewResponse(**row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/untracked-interviews/{untracked_id}/packet",
)
async def get_untracked_interview_packet(
    untracked_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    """Return the captured feedback packet for an untracked interview.

    The standard `/roles/{id}/candidates/{cid}/packet` RPC doesn't surface
    rows under the org's materialized untracked requisition, so the FE's
    PacketDrawer needs a dedicated endpoint that reads the same source CR
    data and emits it in `CandidatePacket` shape. Mirrors v1's
    `/api/v1/requisitions/untracked/interviews/{id}/packet` route in spirit.
    """
    try:
        return await untracked_service.get_untracked_packet(
            supabase,
            org_id=current.organization_id_str,
            source_candidate_round_id=str(untracked_id),
        )
    except UntrackedMutationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/untracked-interviews/{untracked_id}/link-to-existing",
    response_model=LinkToExistingResponse,
)
async def link_untracked_to_existing(
    untracked_id: UUID,
    body: LinkToExistingRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> LinkToExistingResponse:
    """Link an untracked interview into an existing requisition.

    Mirrors the FE "Link to Existing" button. target_round_id is optional;
    when omitted the service picks the requisition's first active round.
    """
    try:
        result = await untracked_service.link_to_existing(
            supabase,
            org_id=current.organization_id_str,
            source_candidate_round_id=str(untracked_id),
            target_requisition_id=str(body.requisition_id),
            target_round_id=str(body.target_round_id) if body.target_round_id else None,
            mode=body.mode,
            target_candidate_id=(
                str(body.target_candidate_id) if body.target_candidate_id else None
            ),
            imported_by_user_id=str(current.user.id) if current.user.id else None,
            interviewer_email=str(body.interviewer_email) if body.interviewer_email else None,
            interviewer_name=body.interviewer_name,
            scheduled_at=body.scheduled_at.isoformat() if body.scheduled_at else None,
        )
    except UntrackedMutationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return LinkToExistingResponse(**result)


@router.post(
    "/untracked-interviews/{untracked_id}/mark-not-interview",
    response_model=MarkNotInterviewResponse,
)
async def mark_untracked_not_interview(
    untracked_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> MarkNotInterviewResponse:
    """Mark an untracked row as 'not an interview' — terminal dismissal.
    Idempotent: re-dismissing a dismissed row is a no-op.
    """
    try:
        result = await untracked_service.mark_not_interview(
            supabase,
            org_id=current.organization_id_str,
            source_candidate_round_id=str(untracked_id),
            actor_user_id=str(current.user.id) if current.user.id else None,
        )
    except UntrackedMutationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return MarkNotInterviewResponse(**result)


@router.post(
    "/untracked-interviews/{untracked_id}/undo",
    response_model=UndoLinkResponse,
)
async def undo_untracked_link_route(
    untracked_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> UndoLinkResponse:
    """Undo the active association: restore the prior round + scorecard,
    disassociate the role, drop the copied transcript + feedback link, and return
    the interview to 'available'. 404 if there is no active association.
    """
    try:
        result = await untracked_service.undo_link(
            supabase,
            org_id=current.organization_id_str,
            source_candidate_round_id=str(untracked_id),
        )
    except UntrackedMutationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return UndoLinkResponse(**result)
