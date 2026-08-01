"""
Candidate packet read endpoint.

Endpoints owned:
  GET /roles/{id}/candidates/{cid}/packet
"""

from uuid import UUID

from app.api.v2.core.exceptions import NotFoundError


async def get_candidate_packet(
    supabase, org_id: str, candidate_id: UUID
) -> dict:
    """Pure pass-through to the `get_candidate_packet` RPC. The RPC returns
    `{candidate: null, rounds: null}` if the candidate is missing or
    cross-org — surface that as 404."""
    result = await supabase.rpc(
        "get_candidate_packet",
        {
            "p_candidate_id": str(candidate_id),
            "p_org_id": org_id,
        },
    )
    data = result.data
    if not data or not data.get("candidate"):
        raise NotFoundError("Candidate not found")
    return data
