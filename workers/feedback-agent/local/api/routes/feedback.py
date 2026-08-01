from fastapi import APIRouter, HTTPException

from src.models import (
    FeedbackBullet,
    FeedbackProcessingRequest,
    FeedbackProcessingResponse,
    TopicFeedbackResult,
)
from src.services import FeedbackPipeline

router = APIRouter(tags=["feedback"])


@router.post("/process-feedback", response_model=FeedbackProcessingResponse)
async def process_feedback(request: FeedbackProcessingRequest):
    pipeline = FeedbackPipeline()

    try:
        result = await pipeline.process(request.transcript, request.topics)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Feedback extraction failed: {e}")

    topic_feedback_results = []

    for topic_id, data in result["condensed_results"].items():
        topic = result["topics_lookup"].get(topic_id)
        if not topic:
            continue

        condensed_items = []
        for item in data["condensed"]:
            condensed_items.append(
                FeedbackBullet(
                    feedback_bullet=item.get("feedback_bullet", ""),
                    antifeedback_bullet=item.get("antifeedback_bullet", ""),
                    sentiment=item.get("sentiment", "neutral"),
                )
            )

        topic_feedback_results.append(
            TopicFeedbackResult(
                topic_id=topic_id,
                heading=topic.heading,
                description=topic.description,
                raw_bullets=data["raw_bullets"],
                condensed_feedback=condensed_items,
            )
        )

    return FeedbackProcessingResponse(
        topic_feedback=topic_feedback_results,
        debug_extracted_bullets=result.get("extracted_bullets"),
    )
