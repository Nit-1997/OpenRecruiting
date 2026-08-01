from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.clients.supabase import get_supabase_client
from src.jobs.processor import JobProcessor
from src.jobs.result_transformer import transform_to_feedback_output
from src.logging import get_logger

router = APIRouter(tags=["rounds"])
logger = get_logger(__name__)


class RoundProcessRequest(BaseModel):
    candidate_round_id: str


class RoundProcessResponse(BaseModel):
    status: str
    candidate_round_id: str
    complete_result: dict
    evidence_result: dict
    judge_result: dict
    summary_result: dict


@router.get("/rounds")
async def list_rounds():
    supabase = get_supabase_client()
    from src.clients.supabase import get_async_http_client

    client = get_async_http_client()

    resp = await client.get(
        f"{supabase.url}/rest/v1/candidate_rounds",
        params={
            "select": "id,status,processing_status,rating,created_at,"
            "candidate:candidates(id,name,email),"
            "round:rounds(id,name,requisition:requisitions(id,role_title))",
            "order": "created_at.desc",
            "limit": "50",
        },
        headers=supabase.headers,
    )

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    rounds_data = resp.json()

    result = []
    for r in rounds_data:
        candidate = r.get("candidate") or {}
        round_info = r.get("round") or {}
        requisition = round_info.get("requisition") or {}

        result.append({
            "id": r["id"],
            "status": r.get("status"),
            "processing_status": r.get("processing_status"),
            "rating": r.get("rating"),
            "created_at": r.get("created_at"),
            "candidate_name": candidate.get("name", "Unknown"),
            "candidate_email": candidate.get("email", ""),
            "round_name": round_info.get("name", "Unknown"),
            "role_title": requisition.get("role_title", "Unknown"),
        })

    return {"rounds": result}


@router.get("/rounds/{candidate_round_id}")
async def get_round_details(candidate_round_id: str):
    supabase = get_supabase_client()
    from src.clients.supabase import get_async_http_client

    client = get_async_http_client()

    cr_resp = await client.get(
        f"{supabase.url}/rest/v1/candidate_rounds",
        params={
            "id": f"eq.{candidate_round_id}",
            "select": "id,status,processing_status,processing_error,rating,summary,created_at,"
            "candidate:candidates(id,name,email,requisition_id),"
            "round:rounds(id,name,description,duration_minutes)",
        },
        headers=supabase.headers,
    )
    cr_data = cr_resp.json()
    if not cr_data:
        raise HTTPException(status_code=404, detail="Candidate round not found")

    cr = cr_data[0]

    transcript_resp = await client.get(
        f"{supabase.url}/rest/v1/transcripts",
        params={
            "candidate_round_id": f"eq.{candidate_round_id}",
            "select": "id,segments,duration_seconds,word_count,feedback_transcript",
        },
        headers=supabase.headers,
    )
    transcript_data = transcript_resp.json()
    has_transcript = bool(transcript_data and transcript_data[0].get("segments"))

    bot_resp = await client.get(
        f"{supabase.url}/rest/v1/recall_bots",
        params={
            "candidate_round_id": f"eq.{candidate_round_id}",
            "select": "id,status,feedback_started_at,joined_at,recording_duration_seconds",
        },
        headers=supabase.headers,
    )
    bot_data = bot_resp.json()

    round_id = cr.get("round", {}).get("id")
    questions_resp = await client.get(
        f"{supabase.url}/rest/v1/feedback_questions",
        params={
            "round_id": f"eq.{round_id}",
            "deleted_at": "is.null",
            "select": "id,question_number,heading,description",
            "order": "question_number.asc",
        },
        headers=supabase.headers,
    )
    questions = questions_resp.json() or []

    candidate = cr.get("candidate") or {}
    requisition_id = candidate.get("requisition_id")

    role_context = {}
    if requisition_id:
        req_resp = await client.get(
            f"{supabase.url}/rest/v1/requisitions",
            params={
                "id": f"eq.{requisition_id}",
                "select": "role_title,role_location,experience_min_years,experience_max_years",
            },
            headers=supabase.headers,
        )
        req_data = req_resp.json()
        if req_data:
            req = req_data[0]
            role_context = {
                "role_title": req.get("role_title"),
                "location": req.get("role_location"),
                "experience": f"{req.get('experience_min_years', 0)}-{req.get('experience_max_years', 'N/A')} years",
            }

    return {
        "candidate_round": {
            "id": cr["id"],
            "status": cr.get("status"),
            "processing_status": cr.get("processing_status"),
            "processing_error": cr.get("processing_error"),
            "rating": cr.get("rating"),
            "summary": cr.get("summary"),
            "created_at": cr.get("created_at"),
        },
        "candidate": {
            "name": candidate.get("name"),
            "email": candidate.get("email"),
        },
        "round": cr.get("round"),
        "role_context": role_context,
        "transcript": {
            "has_segments": has_transcript,
            "segment_count": len(transcript_data[0]["segments"]) if has_transcript else 0,
            "duration_seconds": transcript_data[0].get("duration_seconds") if transcript_data else None,
            "word_count": transcript_data[0].get("word_count") if transcript_data else None,
            "has_feedback_transcript": bool(transcript_data and transcript_data[0].get("feedback_transcript")),
        },
        "bot": bot_data[0] if bot_data else None,
        "scorecard": {
            "question_count": len(questions),
            "questions": questions,
        },
    }


@router.post("/rounds/{candidate_round_id}/process", response_model=RoundProcessResponse)
async def process_round(candidate_round_id: str):
    supabase = get_supabase_client()
    processor = JobProcessor(supabase=supabase)

    try:
        await supabase.update_processing_status(candidate_round_id, "processing")

        segments, feedback_start_ts = await supabase.get_transcript_data(candidate_round_id)
        if not segments:
            raise HTTPException(status_code=400, detail="No transcript segments found")

        questions, questions_map = await supabase.get_scorecard_questions(candidate_round_id)
        if not questions:
            raise HTTPException(status_code=400, detail="No scorecard questions found")

        role_context = await supabase.get_role_context(candidate_round_id)

        result = await processor.process_from_segments(
            segments=segments,
            feedback_start_timestamp=feedback_start_ts,
            questions=questions,
            role_context=role_context,
        )

        judge_result = result.get("judge_result", {})
        summary_result = result.get("summary_result", {})
        feedback_output = transform_to_feedback_output(judge_result, summary_result)

        await supabase.save_feedback_results(candidate_round_id, feedback_output, questions_map)
        await supabase.update_processing_status(candidate_round_id, "completed")

        return RoundProcessResponse(
            status="completed",
            candidate_round_id=candidate_round_id,
            complete_result=result.get("complete_result", {}),
            evidence_result=result.get("evidence_result", {}),
            judge_result=result.get("judge_result", {}),
            summary_result=summary_result,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("process_round_failed", candidate_round_id=candidate_round_id, error=str(e))
        await supabase.update_processing_status(candidate_round_id, "failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
