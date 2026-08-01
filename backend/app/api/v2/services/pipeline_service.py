"""
Pipeline (candidates list) + candidate-level mutations.

Endpoints owned:
  GET    /roles/{id}/candidates                                  → get_role_candidates
  POST   /roles/{id}/candidates                                  → add_candidate
  POST   /roles/{id}/candidates/{cid}/rounds                     → add_custom_round
  DELETE /roles/{id}/candidates/{cid}/rounds/{cr_id}             → delete_candidate_round
"""

import hashlib
from typing import Optional
from uuid import UUID

from app.api.v2.core.rpc import call_rpc
from app.api.v2.schemas.candidate import (
    AddCustomRoundRequest,
    CreateCandidateRequest,
)


# Palette mirrors recruiter-app-v2/src/services/candidates.ts so the API-computed
# colors match whatever the UI would have rendered in mock mode. Spec §15:
# "Computed from name in API response. Not columns."
_AVATAR_PALETTE = ("#EADFD4", "#D8EFE3", "#E9DFF5", "#FDE68A", "#BFDBFE", "#FECACA")


def _initials_for(name: Optional[str]) -> str:
    if not name:
        return "?"
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _avatar_color_for(candidate_id: Optional[str]) -> str:
    """Deterministic by candidate_id so each candidate keeps the same color
    across reloads. Uses md5 (no security need; just a stable hash)."""
    if not candidate_id:
        return _AVATAR_PALETTE[0]
    h = hashlib.md5(candidate_id.encode("utf-8")).digest()
    return _AVATAR_PALETTE[h[0] % len(_AVATAR_PALETTE)]


def _enrich_candidate(c: dict) -> dict:
    """Inject avatar_initials, avatar_color, current_round_id derived fields
    per spec §15. Mutates and returns the same dict."""
    c["avatar_initials"] = _initials_for(c.get("name"))
    c["avatar_color"] = _avatar_color_for(c.get("id"))
    # current_round_id = first non-completed candidate_round (already ordered
    # by round_number in the RPC).
    crs = c.get("candidate_rounds") or []
    next_cr = next((cr for cr in crs if cr.get("status") != "completed"), None)
    c["current_round_id"] = (next_cr or {}).get("round_id")
    return c


def _feedback_questions_payload(qs) -> Optional[list]:
    if not qs:
        return None
    return [
        {
            "heading": q.heading,
            "description": q.description,
            "question_number": q.question_number,
        }
        for q in qs
    ]


# ---------------------------------------------------------------------------
# GET /roles/{role_id}/candidates
# ---------------------------------------------------------------------------


async def get_role_candidates(supabase, org_id: str, role_id: UUID) -> dict:
    """Wraps `get_role_pipeline` and enriches each candidate with the
    derived fields the FE expects per spec §15: avatar_initials,
    avatar_color, current_round_id. The RPC enforces org isolation
    internally — cross-org requisitions get an empty candidates array.
    """
    result = await supabase.rpc(
        "get_role_pipeline",
        {
            "p_req_id": str(role_id),
            "p_org_id": org_id,
        },
    )
    payload = result.data or {"candidates": []}
    candidates = payload.get("candidates") or []
    payload["candidates"] = [_enrich_candidate(c) for c in candidates]
    return payload


# ---------------------------------------------------------------------------
# POST /roles/{role_id}/candidates
# ---------------------------------------------------------------------------


async def add_candidate(
    supabase, org_id: str, role_id: UUID, body: CreateCandidateRequest
) -> dict:
    """Insert a candidate + eager backfill one pending CR per active shared
    round. Spec §15: `source` is accepted for forward-compat and silently
    dropped — no DB column today."""
    data = await call_rpc(
        supabase,
        "add_candidate_with_backfill",
        {
            "p_req_id": str(role_id),
            "p_name": body.name,
            "p_email": str(body.email),
            "p_phone": body.phone,
            "p_resume_url": body.resume_url,
            "p_org_id": org_id,
        },
    )
    return data or {}


# ---------------------------------------------------------------------------
# POST /roles/{role_id}/candidates/{candidate_id}/rounds
# ---------------------------------------------------------------------------


async def add_custom_round(
    supabase,
    org_id: str,
    role_id: UUID,
    candidate_id: UUID,
    body: AddCustomRoundRequest,
) -> dict:
    """Per-candidate custom round (rounds.for_candidate_id IS NOT NULL).
    Custom rounds never appear in the shared plan view; they have their own
    delete path below."""
    data = await call_rpc(
        supabase,
        "add_custom_round",
        {
            "p_req_id": str(role_id),
            "p_candidate_id": str(candidate_id),
            "p_name": body.name,
            "p_category": body.category,
            "p_duration_minutes": body.duration_minutes,
            "p_description": body.description,
            "p_skills": body.skills,
            "p_guidelines": body.guidelines,
            "p_feedback_questions": _feedback_questions_payload(body.feedback_questions),
            "p_org_id": org_id,
        },
    )
    return data or {}


# ---------------------------------------------------------------------------
# DELETE /roles/{role_id}/candidates/{candidate_id}/rounds/{cr_id}
# ---------------------------------------------------------------------------


async def delete_candidate_round(
    supabase,
    org_id: str,
    role_id: UUID,
    candidate_id: UUID,
    cr_id: UUID,
) -> dict:
    """Remove a pending candidate_round. Only `status='pending'` CRs are
    removable. Custom rounds are cleaned up too — the underlying round row
    is deleted when `for_candidate_id IS NOT NULL`."""
    data = await call_rpc(
        supabase,
        "delete_candidate_round",
        {
            "p_req_id": str(role_id),
            "p_candidate_id": str(candidate_id),
            "p_cr_id": str(cr_id),
            "p_org_id": org_id,
        },
    )
    return data or {"deleted_cr_id": str(cr_id), "deleted_round_id": None}
