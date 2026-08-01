from fastapi import APIRouter, HTTPException

from src.models import EvidenceExtractionRequest, EvidenceExtractionResponse
from src.services import EvidenceService

router = APIRouter(tags=["evidence"])


@router.post("/extract-evidence", response_model=EvidenceExtractionResponse)
async def extract_evidence(request: EvidenceExtractionRequest):
    service = EvidenceService()

    try:
        enriched_feedback = await service.extract_all(
            request.chunk_map,
            request.topic_map,
            request.topic_chunk_map,
            request.topic_feedback_map,
        )
        return EvidenceExtractionResponse(enriched_feedback=enriched_feedback)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evidence extraction failed: {e}")
