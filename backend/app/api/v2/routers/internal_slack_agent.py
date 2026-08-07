from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.api.v2.core.dependencies import verify_internal_secret
from app.api.v2.services import team_service
from app.services.supabase import get_supabase_admin_client
from app.services.requisition_service import RequisitionService
from app.models.requisitions import RequisitionCreate
from app.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/internal", dependencies=[Depends(verify_internal_secret)])


class CreateRequisitionRequest(BaseModel):
    org_id: str
    profile_id: str
    role_title: str
    role_location: str = "Remote"
    experience_min_years: int = 0


class InviteTeammateRequest(BaseModel):
    org_id: str
    profile_id: str
    email: str


class AddCandidateRequest(BaseModel):
    org_id: str
    requisition_id: str
    name: str
    email: str
    phone: Optional[str] = None


@router.post("/requisitions")
async def create_requisition(body: CreateRequisitionRequest):
    supabase = get_supabase_admin_client()
    service = RequisitionService(supabase)
    data = RequisitionCreate(
        role_title=body.role_title,
        role_location=body.role_location,
        experience_min_years=body.experience_min_years,
    )
    req = await service.create_requisition(body.org_id, data, body.profile_id)
    return {
        "id": req["id"],
        "title": req.get("role_title", ""),
        "location": req.get("role_location", ""),
        "status": req.get("status", ""),
    }


@router.post("/candidates")
async def add_candidate(body: AddCandidateRequest):
    from app.services.candidate_service import get_candidate_service
    service = get_candidate_service()
    try:
        result = await service.add_candidate(
            requisition_id=body.requisition_id,
            org_id=body.org_id,
            name=body.name,
            email=body.email,
            phone=body.phone,
        )
    except ValueError as e:
        detail = str(e)
        code = 404 if "not found" in detail else 400
        raise HTTPException(status_code=code, detail=detail)

    candidate = result["candidate"]
    rounds = result["rounds"]
    return {
        "id": candidate["id"],
        "name": body.name,
        "email": body.email,
        "requisition": result["role_title"],
        "rounds_assigned": len(rounds),
        "rounds": [
            {
                "candidate_round_id": r["candidate_round_id"],
                "round_name": r.get("name", ""),
                "round_number": r.get("round_number"),
            }
            for r in rounds
        ],
        "message": f"Candidate {body.name} added and assigned to {len(rounds)} interview round(s).",
    }


@router.post("/team/invite")
async def invite_teammate(body: InviteTeammateRequest):
    # Single-sourced through team_service.invite_teammate — same duplicate
    # handling, seat enforcement, expiry, invite-email + phantom-profile
    # creation as the recruiter POST /api/v2/team/invite path. Domain errors
    # (ConflictError/ForbiddenError) propagate to the app-wide v2 handlers,
    # surfacing as proper 409/403 with a {"detail": ...} body — never a
    # 200-with-{"error": ...} envelope.
    supabase = get_supabase_admin_client()
    row = await team_service.invite_teammate(
        supabase,
        org_id=body.org_id,
        invited_by_profile_id=body.profile_id,
        email=body.email,
    )
    return {
        "message": f"Invitation sent to {row.get('email', body.email)}.",
        "email": row.get("email", body.email),
        "invite_id": row.get("id"),
    }
