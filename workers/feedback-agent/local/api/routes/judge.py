from fastapi import APIRouter, HTTPException

from src.models import JudgeRequest, JudgeResponse
from src.services import JudgeService

router = APIRouter(tags=["judge"])


@router.post("/judge-feedback", response_model=JudgeResponse)
async def judge_feedback(request: JudgeRequest):
    service = JudgeService()

    try:
        judged_feedback = await service.judge_all(
            request.enriched_feedback, request.role_context
        )
        return JudgeResponse(
            judged_feedback=judged_feedback,
            role_context_used=request.role_context,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Judgment failed: {e}")
