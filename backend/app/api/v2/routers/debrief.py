"""Recruiter-facing debrief endpoints (spec §9.1).

  GET  /debrief/roles                                  → role picker
  GET  /debrief/roles/{requisition_id}/candidates      → candidate picker (+ tiers)
  POST /debrief/generate                               → generate a draft packet
  POST /debrief/packets/{packet_id}/save               → commit a draft → fresh
  GET  /debrief/packets/{packet_id}                    → poll / fetch a packet
  GET  /debrief/roles/{requisition_id}/packets         → role-tab list (newest first)

Every route is gated by `get_current_user_with_org` (the org wall). Reads are
org-scoped in the repository; generation validates org ownership + eligibility in
the service. The router stays thin: it wires deps, calls service/repository, and
returns DTOs. The service + client are constructed per-request so tests can seam-
mock them via dependency overrides or by patching the factory.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.api.v2.core.exceptions import NotFoundError
from app.api.v2.services.cortex_debrief_client import CortexDebriefClient
from app.api.v2.services.debrief_repository import DebriefRepository
from app.api.v2.services.debrief_service import DebriefService
from app.models.debrief import (
    CandidatePickItem,
    DebriefPacketResponse,
    GenerateDebriefRequest,
    GenerateDebriefResponse,
    PacketListItem,
    RolePickItem,
    SaveDebriefResponse,
)

router = APIRouter(prefix="/debrief", tags=["v2/debrief"])


def _service(supabase) -> DebriefService:
    return DebriefService(
        repository=DebriefRepository(supabase),
        cortex_client=CortexDebriefClient(),
    )


@router.get("/roles", response_model=list[RolePickItem])
async def list_debrief_roles(
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> list[RolePickItem]:
    """Roles with >= 2 debrief-ready candidates."""
    return await DebriefRepository(supabase).roles_with_eligible_candidates(
        current.organization_id_str
    )


@router.get("/roles/{requisition_id}/candidates", response_model=list[CandidatePickItem])
async def list_role_candidates(
    requisition_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> list[CandidatePickItem]:
    """Candidates on a role, each tagged with its eligibility tier."""
    return await DebriefRepository(supabase).candidates_for_role(
        str(requisition_id), current.organization_id_str
    )


@router.post("/generate", response_model=GenerateDebriefResponse)
async def generate_debrief(
    body: GenerateDebriefRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> GenerateDebriefResponse:
    """Generate a draft: persist `generating`, call the Cortex skill inline,
    finalize the packet as a `draft` (NO supersede). The FE previews the draft,
    then commits it via POST /packets/{id}/save. Returns the packet_id + 'draft'."""
    result = await _service(supabase).generate(
        org_id=current.organization_id_str,
        requisition_id=body.requisition_id,
        candidate_ids=body.candidate_ids,
        created_by=str(current.user.id),
    )
    return GenerateDebriefResponse(**result)


@router.post("/packets/{packet_id}/save", response_model=SaveDebriefResponse)
async def save_debrief_packet(
    packet_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> SaveDebriefResponse:
    """Commit a draft packet to `fresh` (advisory-locked supersede of the prior
    fresh for the same natural key). Idempotent on an already-`fresh` packet; 404
    if missing/cross-org; 409 for a non-committable state (generating/failed/
    superseded). Hands off to the role Debrief tab on the FE."""
    result = await _service(supabase).save_draft(
        org_id=current.organization_id_str,
        packet_id=str(packet_id),
    )
    return SaveDebriefResponse(**result)


@router.get("/packets/{packet_id}", response_model=DebriefPacketResponse)
async def get_debrief_packet(
    packet_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> DebriefPacketResponse:
    """Fetch a finalized packet body. 404 while still `generating`/`failed` or if
    cross-org/missing — the FE polls until the body is present."""
    row = await DebriefRepository(supabase).get_packet(
        str(packet_id), current.organization_id_str
    )
    if not row or not row.get("packet"):
        raise NotFoundError("Debrief packet not ready")
    # The PacketBuilder hardcodes status='fresh' in the JSONB; supersede flips only
    # the row COLUMN. Overlay the authoritative row status onto the body so a
    # superseded packet renders the 'Superseded' badge. Only 'fresh'/'superseded'
    # are body-valid here ('generating'/'failed' already 404'd above on no packet).
    body = {**row["packet"], "status": row["status"]}
    return DebriefPacketResponse.model_validate(body)


@router.get("/roles/{requisition_id}/packets", response_model=list[PacketListItem])
async def list_role_packets(
    requisition_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> list[PacketListItem]:
    """Role-tab packet list, newest first."""
    return await DebriefRepository(supabase).list_packets(
        str(requisition_id), current.organization_id_str
    )
