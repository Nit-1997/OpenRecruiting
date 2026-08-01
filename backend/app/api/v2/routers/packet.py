"""
Candidate packet read route.

  GET /roles/{id}/candidates/{cid}/packet
"""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.api.v2.services import packet_service


router = APIRouter(tags=["v2/packet"])


@router.get("/roles/{role_id}/candidates/{candidate_id}/packet")
async def get_candidate_packet(
    role_id: UUID,
    candidate_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    # role_id is part of the URL for consistency but the underlying RPC only
    # needs the candidate_id (and the org for isolation). The RPC returns
    # null candidate for cross-org / missing candidates.
    return await packet_service.get_candidate_packet(
        supabase, current.organization_id_str, candidate_id
    )
