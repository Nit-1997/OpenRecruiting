from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Query
from uuid import UUID
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import asyncio
from app.logging_config import get_logger
from app.dependencies import require_staff, CurrentUser
from app.models.requisitions import (
    CandidateCreate,
    CandidateResponse,
    CandidateWithRoundsResponse,
    CandidateWithRoundsListResponse,
    CandidateHiringPacketResponse,
    CandidateRoundResponse,
    CandidateRoundDetailResponse,
    CandidateFeedbackResponse,
    FeedbackEntryResponse,
    FeedbackQuestionWithFeedbackResponse,
    CandidateStatusUpdate,
    ScheduleInterviewRequest,
    RoundOutcomeUpdate,
    SubmitFeedbackRequest,
    SubmitStructuredFeedbackRequest,
    SubmitFeedbackResponse,
    format_duration,
)
from app.services.supabase import get_supabase_admin_client, insert_many
from app.api.v2.core.rpc import call_rpc

logger = get_logger(__name__)

router = APIRouter(tags=["Candidates"])


class DeleteResponse(BaseModel):
    message: str
    id: UUID


# ============================================
# HELPER FUNCTIONS
# ============================================

def build_candidate_round_response(cr: dict, round_data: dict) -> dict:
    return {
        "id": cr["id"],
        "candidate_id": cr["candidate_id"],
        "round_id": cr["round_id"],
        "round_name": round_data.get("name", ""),
        "round_number": round_data.get("round_number", 0),
        "status": cr["status"],
        "scheduled_at": cr.get("scheduled_at"),
        "completed_at": cr.get("completed_at"),
        "outcome": cr.get("outcome"),
        "outcome_notes": cr.get("outcome_notes"),
        "bot_session_id": cr.get("bot_session_id"),
        "transcript_url": cr.get("transcript_url"),
        "recording_url": cr.get("recording_url"),
        "meeting_url": cr.get("meeting_url"),
        "created_at": cr["created_at"],
        "updated_at": cr["updated_at"],
    }


def build_candidate_with_rounds(candidate: dict, candidate_rounds: List[dict], rounds_map: dict) -> dict:
    rounds = []
    for cr in sorted(candidate_rounds, key=lambda x: rounds_map.get(x["round_id"], {}).get("round_number", 0)):
        round_data = rounds_map.get(cr["round_id"], {})
        rounds.append(build_candidate_round_response(cr, round_data))

    return {
        **candidate,
        "rounds": rounds,
    }


# ============================================
# CANDIDATE CRUD
# ============================================

@router.post(
    "/requisitions/{req_id}/candidates",
    response_model=CandidateWithRoundsResponse,
    status_code=status.HTTP_201_CREATED
)
async def add_candidate(
    req_id: UUID,
    candidate_data: CandidateCreate,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    req_result, rounds_result = await asyncio.gather(
        supabase.table("requisitions").select("id, role_title, status").eq("id", str(req_id)).is_null("deleted_at").single().execute_async(),
        supabase.table("rounds").select("*").eq("requisition_id", str(req_id)).is_null("deleted_at").order("round_number").execute_async()
    )

    if not req_result.data:
        raise HTTPException(status_code=404, detail="Requisition not found")

    rounds = rounds_result.data or []
    if len(rounds) == 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot add candidates to a requisition without an interview plan. Please create rounds first."
        )

    existing = await supabase.table("candidates").select("id").eq("requisition_id", str(req_id)).eq("email", candidate_data.email).is_null("deleted_at").execute_async()
    if existing.data and len(existing.data) > 0:
        raise HTTPException(status_code=400, detail="A candidate with this email already exists for this requisition")

    candidate_insert = {
        "requisition_id": str(req_id),
        "name": candidate_data.name,
        "email": candidate_data.email,
        "phone": candidate_data.phone,
        "resume_url": candidate_data.resume_url,
        "status": "active",
    }

    result = await supabase.table("candidates").insert(candidate_insert).execute_async()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create candidate")

    candidate = result.data if isinstance(result.data, dict) else result.data[0]
    candidate_id = candidate["id"]

    candidate_rounds_data = [
        {
            "candidate_id": candidate_id,
            "round_id": r["id"],
            "status": "pending",
        }
        for r in rounds
    ]

    cr_result = await insert_many(supabase, "candidate_rounds", candidate_rounds_data).execute_async()
    candidate_rounds = cr_result.data or []

    rounds_map = {r["id"]: r for r in rounds}

    return build_candidate_with_rounds(candidate, candidate_rounds, rounds_map)


@router.get(
    "/requisitions/{req_id}/candidates",
    response_model=CandidateWithRoundsListResponse
)
async def list_candidates(
    req_id: UUID,
    status_filter: Optional[str] = None,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    req_result = await supabase.table("requisitions").select("id").eq("id", str(req_id)).is_null("deleted_at").single().execute_async()
    if not req_result.data:
        raise HTTPException(status_code=404, detail="Requisition not found")

    candidates_query = supabase.table("candidates").select("id,requisition_id,name,email,phone,status,final_verdict,created_at,updated_at").eq("requisition_id", str(req_id)).is_null("deleted_at")
    if status_filter:
        candidates_query = candidates_query.eq("status", status_filter)

    candidates_result, rounds_result = await asyncio.gather(
        candidates_query.order("created_at", desc=True).execute_async(),
        supabase.table("rounds").select("*").eq("requisition_id", str(req_id)).is_null("deleted_at").order("round_number").execute_async()
    )

    candidates = candidates_result.data or []
    rounds = rounds_result.data or []
    rounds_map = {r["id"]: r for r in rounds}

    if len(candidates) == 0:
        return CandidateWithRoundsListResponse(candidates=[], total=0)

    candidate_ids = [c["id"] for c in candidates]
    cr_result = await supabase.table("candidate_rounds").select("*").in_("candidate_id", candidate_ids).execute_async()
    all_candidate_rounds = cr_result.data or []

    cr_by_candidate = {}
    for cr in all_candidate_rounds:
        cid = cr["candidate_id"]
        if cid not in cr_by_candidate:
            cr_by_candidate[cid] = []
        cr_by_candidate[cid].append(cr)

    result_candidates = []
    for c in candidates:
        candidate_rounds = cr_by_candidate.get(c["id"], [])
        result_candidates.append(build_candidate_with_rounds(c, candidate_rounds, rounds_map))

    return CandidateWithRoundsListResponse(
        candidates=result_candidates,
        total=len(result_candidates)
    )


@router.get(
    "/candidates/{candidate_id}",
    response_model=CandidateHiringPacketResponse
)
async def get_candidate_hiring_packet(
    candidate_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    candidate_result = await supabase.table("candidates").select("*").eq("id", str(candidate_id)).is_null("deleted_at").single().execute_async()
    if not candidate_result.data:
        raise HTTPException(status_code=404, detail="Candidate not found")

    candidate = candidate_result.data
    req_id = candidate["requisition_id"]

    req_result, rounds_result, cr_result = await asyncio.gather(
        supabase.table("requisitions").select("role_title").eq("id", req_id).single().execute_async(),
        supabase.table("rounds").select("*").eq("requisition_id", req_id).is_null("deleted_at").order("round_number").execute_async(),
        supabase.table("candidate_rounds").select("*").eq("candidate_id", str(candidate_id)).execute_async()
    )

    requisition = req_result.data or {}
    rounds = rounds_result.data or []
    candidate_rounds = cr_result.data or []

    rounds_map = {r["id"]: r for r in rounds}
    cr_map = {cr["round_id"]: cr for cr in candidate_rounds}

    round_ids = [r["id"] for r in rounds]
    cr_ids = [cr["id"] for cr in candidate_rounds]

    assessment_template_ids = [r["assessment_template_id"] for r in rounds if r.get("assessment_template_id")]

    all_feedback = []
    all_questions = []
    all_templates = []
    all_instances = []

    fetch_tasks = []
    if cr_ids and round_ids:
        fetch_tasks.append(supabase.table("candidate_feedback").select("*, feedback_questions(heading, question_number, description)").in_("candidate_round_id", cr_ids).order("created_at").execute_async())
        fetch_tasks.append(supabase.table("feedback_questions").select("*").in_("round_id", round_ids).is_null("deleted_at").order("question_number").execute_async())
    elif round_ids:
        fetch_tasks.append(asyncio.sleep(0))
        fetch_tasks.append(supabase.table("feedback_questions").select("*").in_("round_id", round_ids).is_null("deleted_at").order("question_number").execute_async())
    else:
        fetch_tasks.append(asyncio.sleep(0))
        fetch_tasks.append(asyncio.sleep(0))

    if assessment_template_ids:
        fetch_tasks.append(supabase.table("assessment_templates").select("*").in_("id", assessment_template_ids).execute_async())
        fetch_tasks.append(supabase.table("assessment_instances").select("*").eq("candidate_id", str(candidate_id)).execute_async())
    else:
        fetch_tasks.append(asyncio.sleep(0))
        fetch_tasks.append(asyncio.sleep(0))

    results = await asyncio.gather(*fetch_tasks)

    if cr_ids and round_ids:
        all_feedback = results[0].data if hasattr(results[0], 'data') else []
        all_questions = results[1].data if hasattr(results[1], 'data') else []
    elif round_ids:
        all_questions = results[1].data if hasattr(results[1], 'data') else []

    if assessment_template_ids:
        all_templates = results[2].data if hasattr(results[2], 'data') else []
        all_instances = results[3].data if hasattr(results[3], 'data') else []

    templates_map = {t["id"]: t for t in all_templates}
    instances_by_round = {i["round_id"]: i for i in all_instances if i.get("round_id")}

    feedback_by_cr = {}
    for fb in all_feedback:
        cr_id = fb["candidate_round_id"]
        if cr_id not in feedback_by_cr:
            feedback_by_cr[cr_id] = []
        feedback_by_cr[cr_id].append(fb)

    questions_by_round = {}
    for q in all_questions:
        rid = q["round_id"]
        if rid not in questions_by_round:
            questions_by_round[rid] = []
        questions_by_round[rid].append(q)

    detailed_rounds = []
    completed_count = 0

    for r in rounds:
        cr = cr_map.get(r["id"])
        if not cr:
            continue

        if cr["status"] == "completed":
            completed_count += 1

        round_feedback = feedback_by_cr.get(cr["id"], [])
        round_questions = questions_by_round.get(r["id"], [])

        feedback_by_question = {}
        for fb in round_feedback:
            qid = fb["feedback_question_id"]
            if qid not in feedback_by_question:
                feedback_by_question[qid] = []
            feedback_by_question[qid].append(fb)

        feedback_questions_with_entries = []
        question_summaries = cr.get("question_summaries") or {}
        for q in sorted(round_questions, key=lambda x: x.get("question_number", 0)):
            q_id = q["id"]
            q_num = q.get("question_number", 0)
            related_feedback = feedback_by_question.get(q_id, [])

            feedback_entries = []
            for fb in related_feedback:
                feedback_entries.append({
                    "id": fb["id"],
                    "feedback_data": fb.get("feedback_text"),
                    "evidence": fb.get("evidence") or [],
                    "evidence_status": fb.get("evidence_status"),
                    "source": fb.get("source", "manual"),
                    "created_at": fb["created_at"],
                    "updated_at": fb["updated_at"],
                })

            feedback_questions_with_entries.append({
                "id": q_id,
                "question_number": q_num,
                "heading": q.get("heading", ""),
                "description": q.get("description"),
                "feedback": feedback_entries,
                "summary": question_summaries.get(str(q_num)),
            })

        round_data = {
            "id": cr["id"],
            "candidate_id": cr["candidate_id"],
            "round_id": cr["round_id"],
            "round_name": r.get("name", ""),
            "round_number": r.get("round_number", 0),
            "round_category": r.get("category"),
            "round_type": r.get("round_type", "interview"),
            "round_duration_minutes": r.get("duration_minutes", 45),
            "round_description": r.get("description"),
            "summary": cr.get("summary"),
            "rating": cr.get("rating"),
            "status": cr["status"],
            "scheduled_at": cr.get("scheduled_at"),
            "completed_at": cr.get("completed_at"),
            "outcome": cr.get("outcome"),
            "outcome_notes": cr.get("outcome_notes"),
            "bot_session_id": cr.get("bot_session_id"),
            "transcript_url": cr.get("transcript_url"),
            "recording_url": cr.get("recording_url"),
            "meeting_url": cr.get("meeting_url"),
            "created_at": cr["created_at"],
            "updated_at": cr["updated_at"],
            "feedback_questions": feedback_questions_with_entries,
        }

        if r.get("assessment_template_id"):
            template = templates_map.get(r["assessment_template_id"])
            if template:
                round_data["assessment_template"] = {
                    "id": template["id"],
                    "title": template.get("title"),
                    "description": template.get("description"),
                    "evaluation_rubric": template.get("evaluation_rubric"),
                    "task_definition": template.get("task_definition"),
                }

            instance = instances_by_round.get(r["id"])
            if instance:
                round_data["assessment_instance"] = {
                    "id": instance["id"],
                    "status": instance.get("status"),
                    "access_url": f"{get_settings().ASSESSMENT_UI_URL}/{instance['id']}",
                    "access_code": instance.get("access_code"),
                    "access_code_expires_at": instance.get("access_code_expires_at"),
                    "started_at": instance.get("started_at"),
                    "submitted_at": instance.get("submitted_at"),
                    "submission_data": instance.get("submission_data"),
                    "work_data": instance.get("work_data"),
                    "evaluation_result": instance.get("evaluation_result"),
                    "evaluation_notes": instance.get("evaluation_notes"),
                    "evaluated_at": instance.get("evaluated_at"),
                }

        detailed_rounds.append(round_data)

    overall_progress = f"{completed_count}/{len(rounds)} rounds completed"

    return CandidateHiringPacketResponse(
        **candidate,
        requisition_title=requisition.get("role_title", ""),
        rounds=detailed_rounds,
        overall_progress=overall_progress,
        overall_average_rating=None,
    )


@router.put(
    "/candidates/{candidate_id}/status",
    response_model=CandidateResponse
)
async def update_candidate_status(
    candidate_id: UUID,
    status_update: CandidateStatusUpdate,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    existing = await supabase.table("candidates").select("id").eq("id", str(candidate_id)).is_null("deleted_at").single().execute_async()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Candidate not found")

    update_data = {"status": status_update.status}
    if status_update.final_verdict is not None:
        update_data["final_verdict"] = status_update.final_verdict

    result = await supabase.table("candidates").update(update_data).eq("id", str(candidate_id)).execute_async()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update candidate")

    return result.data if isinstance(result.data, dict) else result.data[0]


@router.delete(
    "/candidates/{candidate_id}",
    response_model=DeleteResponse
)
async def delete_candidate(
    candidate_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    existing = await supabase.table("candidates").select("id").eq("id", str(candidate_id)).is_null("deleted_at").single().execute_async()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Candidate not found")

    deleted_at = datetime.now(timezone.utc).isoformat()
    await supabase.table("candidates").update({"deleted_at": deleted_at}).eq("id", str(candidate_id)).execute_async()

    return DeleteResponse(message="Candidate deleted", id=candidate_id)


# ============================================
# CANDIDATE ROUND OPERATIONS
# ============================================

@router.put(
    "/candidate-rounds/{cr_id}/schedule",
    response_model=CandidateRoundResponse
)
async def schedule_interview(
    cr_id: UUID,
    schedule_data: ScheduleInterviewRequest,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    cr_result = await supabase.table("candidate_rounds")\
        .select("*, rounds(name, round_number), candidates(name, email)")\
        .eq("id", str(cr_id))\
        .single()\
        .execute_async()
    if not cr_result.data:
        raise HTTPException(status_code=404, detail="Candidate round not found")

    cr = cr_result.data
    candidate = cr.get("candidates", {})
    round_data = cr.get("rounds", {})

    recall_warning = None

    if schedule_data.meeting_url:
        from app.services.recall_service import schedule_or_replace_recall_bot
        bot_result = await schedule_or_replace_recall_bot(
            candidate_round_id=str(cr_id),
            meeting_url=schedule_data.meeting_url,
            scheduled_at=schedule_data.scheduled_at,
            candidate_name=candidate.get("name", "Candidate"),
        )
        recall_warning = bot_result.get("recall_warning")

    update_data = {
        "scheduled_at": schedule_data.scheduled_at.isoformat(),
        "meeting_url": schedule_data.meeting_url,
    }
    if cr.get("status") not in ("in_progress",):
        update_data["status"] = "scheduled"

    result = await supabase.table("candidate_rounds").update(update_data).eq("id", str(cr_id)).execute_async()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to schedule interview")
    cr_data = result.data if isinstance(result.data, dict) else result.data[0]
    response = build_candidate_round_response(cr_data, round_data)

    if recall_warning:
        response["recall_warning"] = f"Interview scheduled but recording bot failed: {recall_warning}"

    return response


@router.get(
    "/candidate-rounds/{cr_id}/recording"
)
async def get_recording(
    cr_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    from app.services.recall_service import get_recall_service

    supabase = get_supabase_admin_client()

    bot_result = await supabase.table("recall_bots")\
        .select("*")\
        .eq("candidate_round_id", str(cr_id))\
        .order("created_at", desc=True)\
        .execute_async()

    if not bot_result.data or len(bot_result.data) == 0:
        return {
            "status": "not_scheduled",
            "message": "No recording bot has been scheduled for this interview"
        }

    bot = bot_result.data[0]

    transcript_result = await supabase.table("transcripts")\
        .select("*")\
        .eq("candidate_round_id", str(cr_id))\
        .execute_async()

    transcript = transcript_result.data[0] if transcript_result.data else None

    response = {
        "status": bot["status"],
        "scheduled_at": bot.get("scheduled_at"),
        "joined_at": bot.get("joined_at"),
        "left_at": bot.get("left_at"),
        "error_code": bot.get("error_code"),
        "error_sub_code": bot.get("error_sub_code")
    }

    if bot["status"] == "done":
        recall_service = get_recall_service()
        try:
            recording_data = await recall_service.get_recording_urls(bot["recall_bot_id"])
            if recording_data:
                response["video_url"] = recording_data.get("video_url")
                response["video_duration_seconds"] = recording_data.get("video_duration")
            elif bot.get("recording_url"):
                response["video_url"] = bot["recording_url"]
                response["video_duration_seconds"] = bot.get("recording_duration_seconds")
        except Exception:
            if bot.get("recording_url"):
                response["video_url"] = bot["recording_url"]
                response["video_duration_seconds"] = bot.get("recording_duration_seconds")
        finally:
            await recall_service.close()

        if transcript:
            response["transcript"] = transcript.get("segments")
            response["transcript_duration_seconds"] = transcript.get("duration_seconds")

        response["participants"] = bot.get("participants")

    return response


@router.put(
    "/candidate-rounds/{cr_id}/outcome",
    response_model=CandidateRoundResponse
)
async def update_round_outcome(
    cr_id: UUID,
    outcome_data: RoundOutcomeUpdate,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    cr_result = await supabase.table("candidate_rounds").select("*, rounds(name, round_number)").eq("id", str(cr_id)).single().execute_async()
    if not cr_result.data:
        raise HTTPException(status_code=404, detail="Candidate round not found")

    completed_at = outcome_data.completed_at or datetime.now(timezone.utc)

    update_data = {
        "outcome": outcome_data.outcome,
        "outcome_notes": outcome_data.outcome_notes,
        "completed_at": completed_at.isoformat(),
        "status": "completed",
    }

    result = await supabase.table("candidate_rounds").update(update_data).eq("id", str(cr_id)).execute_async()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update round outcome")

    cr = result.data if isinstance(result.data, dict) else result.data[0]
    round_data = cr_result.data.get("rounds", {})

    return build_candidate_round_response(cr, round_data)


@router.put(
    "/candidate-rounds/{cr_id}/feedback",
    response_model=SubmitFeedbackResponse
)
async def submit_feedback(
    cr_id: UUID,
    feedback_data: SubmitFeedbackRequest,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    cr_result = await supabase.table("candidate_rounds").select("id, round_id").eq("id", str(cr_id)).single().execute_async()
    if not cr_result.data:
        raise HTTPException(status_code=404, detail="Candidate round not found")

    round_id = cr_result.data["round_id"]

    # Question metadata (heading/number) is only needed to shape the response;
    # this is a read, not part of the mutation. Validation of the question ids
    # happens transactionally inside the RPC (raises BAD_QUESTION -> 400).
    questions_result = await supabase.table("feedback_questions").select("id, heading, question_number").eq("round_id", round_id).is_null("deleted_at").execute_async()
    questions_map = {q["id"]: q for q in (questions_result.data or [])}

    # Atomic per-row upsert (migration 106): validate question ids, then
    # insert/update each incoming row in ONE transaction. A failure rolls
    # everything back — no half-written feedback. The RPC raises P0001
    # BAD_QUESTION (-> 400) for a stray question id and FEEDBACK_NOT_FOUND
    # (-> 404) for an update targeting a row not on this candidate round;
    # call_rpc maps both to the right HTTP status. Rows are returned in payload
    # order so the response below matches the prior per-row loop exactly.
    feedback_payload = [
        {
            "id": str(item.id) if item.id else None,
            "feedback_question_id": str(item.feedback_question_id),
            "feedback_text": item.feedback_text,
        }
        for item in feedback_data.feedback
    ]
    written_rows = await call_rpc(
        supabase,
        "admin_submit_candidate_feedback",
        {
            "p_cr_id": str(cr_id),
            "p_source": feedback_data.source,
            "p_feedback": feedback_payload,
        },
    ) or []

    results = []
    for fb in written_rows:
        q = questions_map.get(fb["feedback_question_id"], {})
        results.append({
            "id": fb["id"],
            "feedback_question_id": fb["feedback_question_id"],
            "heading": q.get("heading", ""),
            "question_number": q.get("question_number", 0),
            "feedback_text": fb.get("feedback_text"),
            "evidence": fb.get("evidence") or [],
            "evidence_status": fb.get("evidence_status"),
            "source": fb.get("source", "manual"),
            "created_at": fb["created_at"],
            "updated_at": fb["updated_at"],
        })

    return SubmitFeedbackResponse(
        candidate_round_id=cr_id,
        feedback=results,
        total_submitted=len(results),
    )


@router.get(
    "/candidate-rounds/{cr_id}",
    response_model=CandidateRoundDetailResponse
)
async def get_candidate_round(
    cr_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    cr_result = await supabase.table("candidate_rounds").select("*, rounds(*)").eq("id", str(cr_id)).single().execute_async()
    if not cr_result.data:
        raise HTTPException(status_code=404, detail="Candidate round not found")

    cr = cr_result.data
    round_data = cr.get("rounds", {})
    round_id = cr["round_id"]

    feedback_result, questions_result = await asyncio.gather(
        supabase.table("candidate_feedback").select("*, feedback_questions(heading, question_number, description)").eq("candidate_round_id", str(cr_id)).order("created_at").execute_async(),
        supabase.table("feedback_questions").select("*").eq("round_id", round_id).is_null("deleted_at").order("question_number").execute_async()
    )

    all_feedback = feedback_result.data or []
    all_questions = questions_result.data or []

    feedback_by_question = {}
    for fb in all_feedback:
        qid = fb["feedback_question_id"]
        if qid not in feedback_by_question:
            feedback_by_question[qid] = []
        feedback_by_question[qid].append(fb)

    feedback_questions_with_entries = []
    for q in sorted(all_questions, key=lambda x: x.get("question_number", 0)):
        q_id = q["id"]
        related_feedback = feedback_by_question.get(q_id, [])

        feedback_entries = []
        for fb in related_feedback:
            feedback_entries.append({
                "id": fb["id"],
                "feedback_data": fb.get("feedback_text"),
                "evidence": fb.get("evidence") or [],
                "evidence_status": fb.get("evidence_status"),
                "source": fb.get("source", "manual"),
                "created_at": fb["created_at"],
                "updated_at": fb["updated_at"],
            })

        feedback_questions_with_entries.append({
            "id": q_id,
            "question_number": q.get("question_number", 0),
            "heading": q.get("heading", ""),
            "description": q.get("description"),
            "feedback": feedback_entries,
        })

    return CandidateRoundDetailResponse(
        id=cr["id"],
        candidate_id=cr["candidate_id"],
        round_id=cr["round_id"],
        round_name=round_data.get("name", ""),
        round_number=round_data.get("round_number", 0),
        round_category=round_data.get("category"),
        round_duration_minutes=round_data.get("duration_minutes", 45),
        round_description=round_data.get("description"),
        summary=cr.get("summary"),
        rating=cr.get("rating"),
        status=cr["status"],
        scheduled_at=cr.get("scheduled_at"),
        completed_at=cr.get("completed_at"),
        outcome=cr.get("outcome"),
        outcome_notes=cr.get("outcome_notes"),
        bot_session_id=cr.get("bot_session_id"),
        transcript_url=cr.get("transcript_url"),
        recording_url=cr.get("recording_url"),
        meeting_url=cr.get("meeting_url"),
        created_at=cr["created_at"],
        updated_at=cr["updated_at"],
        feedback_questions=feedback_questions_with_entries,
    )


@router.put(
    "/candidate-rounds/{cr_id}/structured-feedback",
    response_model=CandidateRoundDetailResponse
)
async def update_structured_feedback(
    cr_id: UUID,
    request: SubmitStructuredFeedbackRequest,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    cr_result = await supabase.table("candidate_rounds").select("*, rounds(*)").eq("id", str(cr_id)).single().execute_async()
    if not cr_result.data:
        raise HTTPException(status_code=404, detail="Candidate round not found")

    round_id = cr_result.data["round_id"]

    # We still need the question metadata (heading/number/description) to shape
    # the response below; this is a read, not part of the mutation.
    questions_result = await supabase.table("feedback_questions").select("id, heading, question_number, description").eq("round_id", round_id).is_null("deleted_at").execute_async()

    # Atomic batch upsert (migration 105): validate question ids, update the
    # round summary/rating, delete removed rows, and insert/update incoming rows
    # in ONE transaction. A failure rolls everything back — no half-written
    # feedback. The RPC raises P0001 BAD_QUESTION (→ 400) for a stray question
    # id; call_rpc maps it to the right HTTP status via the global handlers.
    feedback_payload = [
        {
            "id": str(item.id) if item.id else None,
            "feedback_question_id": str(item.feedback_question_id),
            "feedback_data": item.feedback_data,
            "evidence": item.evidence or [],
            "evidence_status": item.evidence_status,
        }
        for item in request.feedback
    ]
    rpc_result = await call_rpc(
        supabase,
        "admin_set_structured_feedback",
        {
            "p_cr_id": str(cr_id),
            "p_summary": request.round_summary,
            "p_rating": request.round_rating,
            "p_source": request.source,
            "p_feedback": feedback_payload,
        },
    )

    cr = (rpc_result or {}).get("candidate_round") or {}
    round_data = cr.get("rounds") or cr_result.data.get("rounds", {})

    all_feedback = (rpc_result or {}).get("entries") or []
    all_questions = questions_result.data or []

    feedback_by_question = {}
    for fb in all_feedback:
        qid = fb["feedback_question_id"]
        if qid not in feedback_by_question:
            feedback_by_question[qid] = []
        feedback_by_question[qid].append(fb)

    feedback_questions_with_entries = []
    for q in sorted(all_questions, key=lambda x: x.get("question_number", 0)):
        q_id = q["id"]
        related_feedback = feedback_by_question.get(q_id, [])

        feedback_entries = []
        for fb in related_feedback:
            feedback_entries.append({
                "id": fb["id"],
                "feedback_data": fb.get("feedback_text"),
                "evidence": fb.get("evidence") or [],
                "evidence_status": fb.get("evidence_status"),
                "source": fb.get("source", "manual"),
                "created_at": fb["created_at"],
                "updated_at": fb["updated_at"],
            })

        feedback_questions_with_entries.append({
            "id": q_id,
            "question_number": q.get("question_number", 0),
            "heading": q.get("heading", ""),
            "description": q.get("description"),
            "feedback": feedback_entries,
        })

    return CandidateRoundDetailResponse(
        id=cr["id"],
        candidate_id=cr["candidate_id"],
        round_id=cr["round_id"],
        round_name=round_data.get("name", ""),
        round_number=round_data.get("round_number", 0),
        round_category=round_data.get("category"),
        round_duration_minutes=round_data.get("duration_minutes", 45),
        round_description=round_data.get("description"),
        summary=cr.get("summary"),
        rating=cr.get("rating"),
        status=cr["status"],
        scheduled_at=cr.get("scheduled_at"),
        completed_at=cr.get("completed_at"),
        outcome=cr.get("outcome"),
        outcome_notes=cr.get("outcome_notes"),
        bot_session_id=cr.get("bot_session_id"),
        transcript_url=cr.get("transcript_url"),
        recording_url=cr.get("recording_url"),
        meeting_url=cr.get("meeting_url"),
        created_at=cr["created_at"],
        updated_at=cr["updated_at"],
        feedback_questions=feedback_questions_with_entries,
    )



@router.get(
    "/candidate-rounds/{cr_id}/transcript-status",
    summary="Check if transcript exists for a candidate round"
)
async def get_transcript_status(
    cr_id: UUID,
    current_user: CurrentUser = Depends(require_staff),
):
    supabase = get_supabase_admin_client()

    cr_result = await supabase.table("candidate_rounds")\
        .select("id")\
        .eq("id", str(cr_id))\
        .execute_async()

    if not cr_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate round not found"
        )

    transcript_result = await supabase.table("transcripts")\
        .select("segments, feedback_transcript")\
        .eq("candidate_round_id", str(cr_id))\
        .execute_async()

    segments = None
    stored_feedback = None
    if transcript_result.data:
        segments = transcript_result.data[0].get("segments")
        stored_feedback = transcript_result.data[0].get("feedback_transcript")

    bot_result = await supabase.table("recall_bots")\
        .select("feedback_started_at, joined_at")\
        .eq("candidate_round_id", str(cr_id))\
        .execute_async()

    feedback_start_timestamp = None
    if bot_result.data and bot_result.data[0].get("feedback_started_at"):
        feedback_started_at = bot_result.data[0]["feedback_started_at"]
        joined_at = bot_result.data[0].get("joined_at")
        if feedback_started_at and joined_at:
            from dateutil import parser
            feedback_dt = parser.isoparse(feedback_started_at)
            joined_dt = parser.isoparse(joined_at)
            feedback_start_timestamp = (feedback_dt - joined_dt).total_seconds()

    has_segments = bool(segments and len(segments) > 0)
    has_feedback_timestamp = bool(feedback_start_timestamp)
    has_stored_feedback = bool(stored_feedback)

    return {
        "has_transcript": has_segments or has_stored_feedback,
        "has_interview_segments": has_segments,
        "has_feedback_timestamp": has_feedback_timestamp,
        "has_stored_feedback": has_stored_feedback,
        "can_process_existing": has_segments or has_stored_feedback
    }


class CriterionScore(BaseModel):
    criterion_id: str
    criterion_name: str
    score: int = Field(..., ge=0, description="Points earned for this criterion")
    max_points: int = Field(..., ge=1, description="Maximum possible points")
    level: str = Field(..., description="Performance level: excellent, good, adequate, or poor")
    notes: Optional[str] = None


class CategoryScore(BaseModel):
    category_name: str
    category_index: int
    weight_percentage: int
    criterion_scores: List[CriterionScore]


class SubmitAssessmentEvaluationRequest(BaseModel):
    category_scores: List[CategoryScore]
    overall_notes: Optional[str] = None
    strengths: Optional[str] = None
    areas_for_development: Optional[str] = None
    round_summary: Optional[str] = None
    round_rating: Optional[str] = None


@router.put(
    "/candidate-rounds/{cr_id}/assessment-evaluation",
    summary="Submit or update assessment evaluation for a candidate round"
)
async def update_assessment_evaluation(
    cr_id: UUID,
    request: SubmitAssessmentEvaluationRequest,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    cr_result = await supabase.table("candidate_rounds")\
        .select("*, rounds(*, assessment_template_id, assessment_templates(evaluation_rubric))")\
        .eq("id", str(cr_id))\
        .single()\
        .execute_async()

    if not cr_result.data:
        raise HTTPException(status_code=404, detail="Candidate round not found")

    cr = cr_result.data
    round_data = cr.get("rounds", {})

    if not round_data.get("assessment_template_id"):
        raise HTTPException(status_code=400, detail="This round is not an assessment type")

    instance_result = await supabase.table("assessment_instances")\
        .select("id")\
        .eq("round_id", round_data["id"])\
        .eq("candidate_id", cr["candidate_id"])\
        .order("created_at", desc=True)\
        .execute_async()

    if not instance_result.data:
        raise HTTPException(status_code=400, detail="No assessment instance found for this candidate round")

    instance_id = instance_result.data[0]["id"]

    rubric = round_data.get("assessment_templates", {}).get("evaluation_rubric", {})
    rubric_metadata = rubric.get("rubric_metadata", {})
    total_possible_points = rubric_metadata.get("total_possible_points", 100)
    passing_threshold = rubric_metadata.get("passing_threshold_percentage", 70)

    overall_score = 0
    category_results = []

    for cat_score in request.category_scores:
        cat_total = 0
        cat_max = 0
        criterion_results = []

        for crit in cat_score.criterion_scores:
            cat_total += crit.score
            cat_max += crit.max_points
            criterion_results.append({
                "criterion_id": crit.criterion_id,
                "criterion_name": crit.criterion_name,
                "score": crit.score,
                "max_points": crit.max_points,
                "level": crit.level,
                "notes": crit.notes
            })

        cat_percentage = round((cat_total / cat_max * 100) if cat_max > 0 else 0, 1)
        overall_score += cat_total

        category_results.append({
            "category_name": cat_score.category_name,
            "category_index": cat_score.category_index,
            "weight_percentage": cat_score.weight_percentage,
            "score": cat_total,
            "max_score": cat_max,
            "percentage": cat_percentage,
            "criterion_scores": criterion_results
        })

    overall_percentage = round((overall_score / total_possible_points * 100) if total_possible_points > 0 else 0, 1)
    passed = overall_percentage >= passing_threshold

    evaluation_result = {
        "overall_score": overall_score,
        "total_possible_points": total_possible_points,
        "overall_percentage": overall_percentage,
        "passing_threshold": passing_threshold,
        "passed": passed,
        "category_scores": category_results,
        "strengths": request.strengths,
        "areas_for_development": request.areas_for_development,
    }

    await supabase.table("assessment_instances")\
        .update({
            "status": "evaluated",
            "evaluation_result": evaluation_result,
            "evaluation_notes": request.overall_notes,
            "evaluated_at": datetime.now(timezone.utc).isoformat()
        })\
        .eq("id", instance_id)\
        .execute_async()

    round_update = {}
    if request.round_summary is not None:
        round_update["summary"] = request.round_summary
    if request.round_rating is not None:
        round_update["rating"] = request.round_rating

    if round_update:
        await supabase.table("candidate_rounds")\
            .update(round_update)\
            .eq("id", str(cr_id))\
            .execute_async()

    return {
        "candidate_round_id": str(cr_id),
        "assessment_instance_id": instance_id,
        "evaluation_result": evaluation_result,
        "passed": passed,
        "overall_percentage": overall_percentage
    }


@router.get(
    "/candidate-rounds/{cr_id}/assessment-evaluation",
    summary="Get assessment evaluation for a candidate round"
)
async def get_assessment_evaluation(
    cr_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    cr_result = await supabase.table("candidate_rounds")\
        .select("*, rounds(*, assessment_template_id)")\
        .eq("id", str(cr_id))\
        .single()\
        .execute_async()

    if not cr_result.data:
        raise HTTPException(status_code=404, detail="Candidate round not found")

    cr = cr_result.data
    round_data = cr.get("rounds", {})

    if not round_data.get("assessment_template_id"):
        raise HTTPException(status_code=400, detail="This round is not an assessment type")

    instance_result = await supabase.table("assessment_instances")\
        .select("id, status, evaluation_result, evaluation_notes, evaluated_at")\
        .eq("round_id", round_data["id"])\
        .eq("candidate_id", cr["candidate_id"])\
        .order("created_at", desc=True)\
        .execute_async()

    if not instance_result.data:
        return {
            "candidate_round_id": str(cr_id),
            "assessment_instance_id": None,
            "evaluation_result": None,
            "evaluation_notes": None,
            "evaluated_at": None,
            "round_summary": cr.get("summary"),
            "round_rating": cr.get("rating")
        }

    instance = instance_result.data[0]

    return {
        "candidate_round_id": str(cr_id),
        "assessment_instance_id": instance["id"],
        "evaluation_result": instance.get("evaluation_result"),
        "evaluation_notes": instance.get("evaluation_notes"),
        "evaluated_at": instance.get("evaluated_at"),
        "round_summary": cr.get("summary"),
        "round_rating": cr.get("rating")
    }


import secrets
import hashlib
from datetime import timedelta
from app.config import get_settings


def generate_access_code(length: int = 8) -> str:
    chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    return ''.join(secrets.choice(chars) for _ in range(length))


def hash_access_code(code: str) -> str:
    return hashlib.sha256(code.upper().encode()).hexdigest()


def generate_instance_id() -> str:
    chars = 'abcdefghijklmnopqrstuvwxyz0123456789'
    suffix = ''.join(secrets.choice(chars) for _ in range(8))
    return f"inst_{suffix}"


@router.post(
    "/candidate-rounds/{cr_id}/reschedule-assessment",
    summary="Reschedule assessment - creates a new instance with fresh access code"
)
async def reschedule_assessment(
    cr_id: UUID,
    expiration_days: int = Query(default=3, ge=1, le=30, description="Days until assessment code expires"),
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    cr_result = await supabase.table("candidate_rounds")\
        .select("*, rounds(id, assessment_template_id), candidates(id, name, email)")\
        .eq("id", str(cr_id))\
        .single()\
        .execute_async()

    if not cr_result.data:
        raise HTTPException(status_code=404, detail="Candidate round not found")

    round_data = cr_result.data.get("rounds", {})
    assessment_template_id = round_data.get("assessment_template_id")

    if not assessment_template_id:
        raise HTTPException(status_code=400, detail="This round is not an assessment")

    round_id = round_data.get("id")
    existing = await supabase.table("assessment_instances")\
        .select("id")\
        .eq("round_id", str(round_id))\
        .execute_async()

    for old_instance in (existing.data or []):
        await supabase.table("assessment_instances")\
            .update({"status": "expired"})\
            .eq("id", old_instance["id"])\
            .execute_async()

    candidate_data = cr_result.data.get("candidates", {})
    candidate_id = candidate_data.get("id", "")
    candidate_email = candidate_data.get("email", "")
    candidate_name = candidate_data.get("name", "")

    access_code = generate_access_code(8)
    expiry_date = datetime.now(timezone.utc) + timedelta(days=expiration_days)

    instance_data = {
        "id": generate_instance_id(),
        "template_id": assessment_template_id,
        "candidate_id": str(candidate_id),
        "candidate_email": candidate_email,
        "candidate_name": candidate_name,
        "access_code": access_code,
        "access_code_hash": hash_access_code(access_code),
        "access_code_expires_at": expiry_date.isoformat(),
        "status": "pending",
        "expires_at": expiry_date.isoformat(),
        "round_id": str(round_id),
    }

    result = await supabase.table("assessment_instances").insert(instance_data).execute_async()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create assessment instance")

    new_instance = result.data[0] if isinstance(result.data, list) else result.data

    return {
        "instance_id": new_instance["id"],
        "access_url": f"{get_settings().ASSESSMENT_UI_URL}/{new_instance['id']}",
        "access_code": access_code,
        "access_code_expires_at": new_instance["access_code_expires_at"],
        "expires_at": new_instance["expires_at"],
        "status": new_instance["status"],
        "message": "New assessment instance created. Share the new link and code with the candidate."
    }


@router.get(
    "/candidate-rounds/{cr_id}/assessment-instance",
    summary="Get assessment instance details for a candidate round"
)
async def get_assessment_instance(
    cr_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    cr_result = await supabase.table("candidate_rounds")\
        .select("*, rounds(id, assessment_template_id)")\
        .eq("id", str(cr_id))\
        .single()\
        .execute_async()

    if not cr_result.data:
        raise HTTPException(status_code=404, detail="Candidate round not found")

    round_data = cr_result.data.get("rounds", {})
    if not round_data.get("assessment_template_id"):
        raise HTTPException(status_code=400, detail="This round is not an assessment")

    instance_result = await supabase.table("assessment_instances")\
        .select("*")\
        .eq("round_id", round_data["id"])\
        .eq("candidate_id", cr_result.data["candidate_id"])\
        .order("created_at", desc=True)\
        .limit(1)\
        .execute_async()

    if not instance_result.data:
        return {
            "candidate_round_id": str(cr_id),
            "assessment_instance": None
        }

    instance = instance_result.data[0]
    return {
        "candidate_round_id": str(cr_id),
        "assessment_instance": {
            "instance_id": instance["id"],
            "access_url": f"{get_settings().ASSESSMENT_UI_URL}/{instance['id']}",
            "access_code": instance.get("access_code"),
            "access_code_expires_at": instance.get("access_code_expires_at"),
            "expires_at": instance.get("expires_at"),
            "status": instance.get("status"),
        }
    }
