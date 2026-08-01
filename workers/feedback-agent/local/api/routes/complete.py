from fastapi import APIRouter, HTTPException

from src.models import CompleteProcessingRequest, CompleteProcessingResponse
from src.services import FeedbackOrchestrator

router = APIRouter(tags=["complete"])


@router.post("/process-complete", response_model=CompleteProcessingResponse)
async def process_complete(request: CompleteProcessingRequest):
    orchestrator = FeedbackOrchestrator()

    try:
        result = await orchestrator.process_complete(
            request.interview_transcript,
            request.feedback_transcript,
            request.topics,
            request.candidate_name,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {e}")
