from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.api.v2.core.dependencies import verify_internal_secret
from app.api.v2.services import team_service
from app.services.supabase import get_supabase_admin_client
from app.services.requisition_service import RequisitionService
from app.services.intake_call_service import get_intake_call_service
from app.services.google_calendar_service import get_google_calendar_service
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


class IntakeCallRequest(BaseModel):
    profile_id: str
    org_id: str
    requisition_id: str


class CalendarSlotsRequest(BaseModel):
    profile_id: str
    start_date: str
    end_date: str
    duration_minutes: int = 30
    start_hour: int = 9
    end_hour: int = 17


class ScheduleInterviewRequest(BaseModel):
    profile_id: str
    org_id: str
    candidate_round_id: str
    title: str
    start: str
    end: str
    attendees: list[str] = []
    timezone: Optional[str] = None


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


@router.post("/intake-call")
async def start_intake_call(body: IntakeCallRequest):
    service = get_intake_call_service()
    try:
        result = await service.start_intake_call(
            profile_id=body.profile_id,
            org_id=body.org_id,
            requisition_id=body.requisition_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "intake_call_url": result["intake_call_url"],
        "calendar_event_link": result.get("calendar_event_link"),
        "message": "Intake call ready. Click the link to start your intake call directly in OpenRecruiting.",
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


@router.post("/calendar/slots")
async def find_calendar_slots(body: CalendarSlotsRequest):
    service = get_google_calendar_service()
    result = await service.find_available_slots(
        profile_id=body.profile_id,
        start_date=body.start_date,
        end_date=body.end_date,
        duration_minutes=body.duration_minutes,
        start_hour=body.start_hour,
        end_hour=body.end_hour,
    )
    return result


@router.post("/calendar/schedule")
async def schedule_interview(body: ScheduleInterviewRequest):
    from datetime import datetime, timezone as tz

    supabase = get_supabase_admin_client()

    cr_result = await supabase.table("candidate_rounds") \
        .select("*, candidates(id, name, email, requisition_id)") \
        .eq("id", body.candidate_round_id) \
        .single() \
        .execute_async()
    if not cr_result.data:
        raise HTTPException(status_code=404, detail="Candidate round not found")

    calendar_service = get_google_calendar_service()
    event = await calendar_service.create_meet_event(
        profile_id=body.profile_id,
        title=body.title,
        start=body.start,
        end=body.end,
        attendees=body.attendees or None,
        timezone_override=body.timezone,
    )

    meet_link = event.get("meet_link", "")
    scheduled_at = datetime.fromisoformat(body.start)
    if scheduled_at.tzinfo is None:
        from zoneinfo import ZoneInfo
        try:
            user_tz = ZoneInfo(body.timezone) if body.timezone else tz.utc
        except Exception:
            user_tz = tz.utc
        scheduled_at = scheduled_at.replace(tzinfo=user_tz).astimezone(tz.utc)

    recall_warning = None
    if meet_link:
        from app.services.recall_service import schedule_or_replace_recall_bot
        candidate_name = cr_result.data.get("candidates", {}).get("name", "Candidate")
        bot_result = await schedule_or_replace_recall_bot(
            candidate_round_id=body.candidate_round_id,
            meeting_url=meet_link,
            scheduled_at=scheduled_at,
            candidate_name=candidate_name,
        )
        recall_warning = bot_result.get("recall_warning")

    update_data = {
        "scheduled_at": scheduled_at.isoformat(),
        "meeting_url": meet_link,
    }
    cr_status = cr_result.data.get("status")
    if cr_status not in ("in_progress",):
        update_data["status"] = "scheduled"
    if body.timezone:
        update_data["scheduling_timezone"] = body.timezone
    await supabase.table("candidate_rounds") \
        .update(update_data) \
        .eq("id", body.candidate_round_id) \
        .execute_async()

    result = {
        "event_id": event.get("event_id"),
        "meet_link": meet_link,
        "html_link": event.get("html_link"),
        "candidate_round_id": body.candidate_round_id,
        "status": "scheduled",
    }
    if recall_warning:
        result["recall_warning"] = recall_warning
    return result


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
