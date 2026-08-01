import hmac
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.config import get_settings
from app.services.supabase import get_supabase_admin_client
from app.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/internal")


async def verify_internal_secret(request: Request):
    settings = get_settings()
    secret = request.headers.get("X-Internal-Secret", "")
    if not settings.INTERNAL_API_SECRET or not hmac.compare_digest(secret, settings.INTERNAL_API_SECRET):
        raise HTTPException(status_code=403, detail="Forbidden")


class CalendarIntelligenceScheduleRequest(BaseModel):
    detection_id: str
    candidate_name: str
    candidate_email: str
    requisition_id: str
    round_id: str
    meeting_url: Optional[str] = None
    scheduled_at: Optional[str] = None
    recall_event_id: Optional[str] = None


@router.post("/calendar-intelligence/schedule")
async def schedule_from_detection(
    body: CalendarIntelligenceScheduleRequest,
    request: Request,
):
    await verify_internal_secret(request)

    from app.config import get_settings
    if not get_settings().CALENDAR_INTELLIGENCE_ENABLED:
        raise HTTPException(503, "Calendar Intelligence is temporarily disabled")

    supabase = get_supabase_admin_client()

    SCHEDULABLE_STATUSES = {
        "detected", "notified", "awaiting_role", "awaiting_round", "awaiting_confirm",
        "orphan_no_response", "orphan_role", "orphan_round", "orphan_confirm",
    }

    detection = await supabase.table("calendar_event_detections") \
        .select("id, detection_status, organization_id, profile_id") \
        .eq("id", body.detection_id) \
        .execute_async()
    if not detection.data:
        raise HTTPException(404, "Detection not found")
    det_row = detection.data[0]

    current_status = det_row["detection_status"]
    if current_status not in SCHEDULABLE_STATUSES:
        raise HTTPException(409, f"Detection already in terminal state: {current_status}")

    cas_claim = await supabase.table("calendar_event_detections") \
        .update({"detection_status": "confirming", "updated_at": datetime.now(timezone.utc).isoformat()}) \
        .eq("id", body.detection_id) \
        .eq("detection_status", current_status) \
        .execute_async()
    if not cas_claim.data:
        raise HTTPException(409, "Detection state changed concurrently")

    try:
        return await _execute_schedule(body, supabase, current_status, det_row)
    except Exception:
        await supabase.table("calendar_event_detections") \
            .update({"detection_status": current_status, "updated_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("id", body.detection_id) \
            .eq("detection_status", "confirming") \
            .execute_async()
        raise


async def _execute_schedule(body: CalendarIntelligenceScheduleRequest, supabase, original_status: str, det_row: dict):
    req_result = await supabase.table("requisitions") \
        .select("id, organization_id") \
        .eq("id", body.requisition_id) \
        .is_("deleted_at", "null") \
        .execute_async()
    if not req_result.data:
        raise HTTPException(404, "Requisition not found")
    req_row = req_result.data[0]

    if str(req_row.get("organization_id")) != str(det_row.get("organization_id")):
        raise HTTPException(400, "Requisition does not belong to detection's organization")

    round_result = await supabase.table("rounds") \
        .select("id, round_number, requisition_id") \
        .eq("id", body.round_id) \
        .is_("deleted_at", "null") \
        .execute_async()
    if not round_result.data:
        raise HTTPException(404, "Round not found")

    if str(round_result.data[0].get("requisition_id")) != str(body.requisition_id):
        raise HTTPException(400, "Round does not belong to the specified requisition")

    candidate_id = None
    candidate_was_created = False

    if body.candidate_email:
        existing = await supabase.table("candidates") \
            .select("id") \
            .eq("requisition_id", body.requisition_id) \
            .eq("email", body.candidate_email.lower()) \
            .is_("deleted_at", "null") \
            .execute_async()

        if existing.data:
            candidate_id = existing.data[0]["id"]
        else:
            from app.services.candidate_service import get_candidate_service
            org_id = det_row.get("organization_id") or req_row.get("organization_id")
            try:
                cand_svc = get_candidate_service()
                result = await cand_svc.add_candidate(
                    requisition_id=body.requisition_id,
                    org_id=org_id,
                    name=body.candidate_name or "Unknown",
                    email=body.candidate_email.lower(),
                )
                candidate_id = result["candidate"]["id"]
                candidate_was_created = True
            except ValueError as e:
                if "already exists" in str(e):
                    re_check = await supabase.table("candidates") \
                        .select("id") \
                        .eq("requisition_id", body.requisition_id) \
                        .eq("email", body.candidate_email.lower()) \
                        .is_("deleted_at", "null") \
                        .execute_async()
                    if re_check.data:
                        candidate_id = re_check.data[0]["id"]
                    else:
                        raise HTTPException(400, str(e))
                else:
                    raise HTTPException(400, str(e))

    if not candidate_id:
        raise HTTPException(400, "Failed to create or find candidate")

    cr_was_new = False
    prior_cr_state = None
    candidate_round_id = None

    try:
        existing_cr = await supabase.table("candidate_rounds") \
            .select("id, status, meeting_url, scheduled_at") \
            .eq("candidate_id", candidate_id) \
            .eq("round_id", body.round_id) \
            .execute_async()

        if existing_cr.data:
            cr_row = existing_cr.data[0]
            cr_status = cr_row.get("status")
            if cr_status in ("completed", "in_progress"):
                raise HTTPException(409, f"Round already {cr_status} — cannot reuse for new interview")
            candidate_round_id = cr_row["id"]
            prior_cr_state = {
                "status": cr_status,
                "meeting_url": cr_row.get("meeting_url"),
                "scheduled_at": cr_row.get("scheduled_at"),
            }
            if cr_status in ("pending", "scheduled", "cancelled"):
                await supabase.table("candidate_rounds") \
                    .update({
                        "status": "scheduled",
                        "meeting_url": body.meeting_url,
                        "scheduled_at": body.scheduled_at,
                    }) \
                    .eq("id", candidate_round_id) \
                    .execute_async()
        else:
            cr_result = await supabase.table("candidate_rounds").insert({
                "candidate_id": candidate_id,
                "round_id": body.round_id,
                "status": "scheduled",
                "meeting_url": body.meeting_url,
                "scheduled_at": body.scheduled_at,
            }).execute_async()

            if not cr_result.data:
                raise HTTPException(500, "Failed to create candidate round")

            cr_data = cr_result.data[0] if isinstance(cr_result.data, list) else cr_result.data
            cr_was_new = True
            candidate_round_id = cr_data["id"]
    except HTTPException:
        raise
    except Exception:
        if candidate_was_created and candidate_id:
            await supabase.table("candidates") \
                .update({"deleted_at": datetime.now(timezone.utc).isoformat()}) \
                .eq("id", str(candidate_id)) \
                .execute_async()
        raise

    try:
        bot_result = await supabase.table("recall_bots") \
            .select("id, recall_bot_id, recording_url, transcript_url, transcript_ready") \
            .eq("detection_id", body.detection_id) \
            .execute_async()

        if bot_result.data:
            bot = bot_result.data[0]
            await supabase.table("recall_bots") \
                .update({"candidate_round_id": candidate_round_id}) \
                .eq("id", bot["id"]) \
                .execute_async()

            if bot.get("transcript_ready") and bot.get("transcript_url"):
                try:
                    import httpx
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        resp = await client.get(bot["transcript_url"])
                        if resp.status_code == 200:
                            transcript_data = resp.json()
                            await supabase.table("transcripts").upsert({
                                "candidate_round_id": candidate_round_id,
                                "segments": transcript_data,
                                "raw_transcript_url": bot["transcript_url"],
                                "processed_at": datetime.now(timezone.utc).isoformat(),
                            }, on_conflict="candidate_round_id").execute_async()

                            from app.services.feedback_job_service import get_feedback_job_service
                            feedback_service = get_feedback_job_service()
                            await feedback_service.trigger_feedback_processing(candidate_round_id)
                except Exception as e:
                    logger.error(f"Calendar Intelligence schedule: transcript link failed: {e}")
        else:
            if body.meeting_url and body.scheduled_at:
                from app.services.recall_service import schedule_or_replace_recall_bot
                scheduled_at = datetime.fromisoformat(body.scheduled_at)
                await schedule_or_replace_recall_bot(
                    candidate_round_id=candidate_round_id,
                    meeting_url=body.meeting_url,
                    scheduled_at=scheduled_at,
                    candidate_name=body.candidate_name or "Candidate",
                )
    except Exception:
        now_rb = datetime.now(timezone.utc).isoformat()
        if candidate_was_created and candidate_id:
            await supabase.table("candidates") \
                .update({"deleted_at": now_rb}) \
                .eq("id", str(candidate_id)) \
                .execute_async()
        if candidate_round_id:
            if cr_was_new:
                await supabase.table("candidate_rounds") \
                    .update({"status": "cancelled", "updated_at": now_rb}) \
                    .eq("id", str(candidate_round_id)) \
                    .execute_async()
            elif prior_cr_state:
                restore = {"updated_at": now_rb}
                for f in ("status", "meeting_url", "scheduled_at"):
                    if f in prior_cr_state:
                        restore[f] = prior_cr_state[f]
                await supabase.table("candidate_rounds") \
                    .update(restore) \
                    .eq("id", str(candidate_round_id)) \
                    .execute_async()
        raise

    now = datetime.now(timezone.utc).isoformat()
    final_cas = await supabase.table("calendar_event_detections") \
        .update({
            "detection_status": "confirmed",
            "matched_requisition_id": body.requisition_id,
            "matched_candidate_id": str(candidate_id),
            "matched_candidate_round_id": str(candidate_round_id),
            "candidate_was_created": candidate_was_created,
            "responded_at": now,
            "updated_at": now,
        }) \
        .eq("id", body.detection_id) \
        .eq("detection_status", "confirming") \
        .execute_async()

    if not final_cas.data:
        now_rb = datetime.now(timezone.utc).isoformat()
        if candidate_was_created and candidate_id:
            await supabase.table("candidates") \
                .update({"deleted_at": now_rb}) \
                .eq("id", str(candidate_id)) \
                .execute_async()
        if candidate_round_id:
            if cr_was_new:
                await supabase.table("candidate_rounds") \
                    .update({"status": "cancelled", "updated_at": now_rb}) \
                    .eq("id", str(candidate_round_id)) \
                    .execute_async()
            elif prior_cr_state:
                restore = {"updated_at": now_rb}
                for f in ("status", "meeting_url", "scheduled_at"):
                    if f in prior_cr_state:
                        restore[f] = prior_cr_state[f]
                await supabase.table("candidate_rounds") \
                    .update(restore) \
                    .eq("id", str(candidate_round_id)) \
                    .execute_async()
        raise HTTPException(409, "Detection state changed during processing")

    return {
        "candidate_id": str(candidate_id),
        "candidate_round_id": str(candidate_round_id),
        "candidate_was_created": candidate_was_created,
        "detection_status": "confirmed",
    }


@router.post("/calendar-intelligence/backfill")
async def backfill_recall_registrations(request: Request):
    await verify_internal_secret(request)
    from app.services.google_calendar_service import get_google_calendar_service
    service = get_google_calendar_service()
    result = await service.backfill_recall_registrations()
    return result
