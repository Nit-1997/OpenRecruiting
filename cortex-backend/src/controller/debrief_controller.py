"""Debrief controller — POST /api/v1/debrief (spec §8).

First read endpoint on cortex-backend. Mirrors the ingestion controller's auth
(`X-Internal-Secret` via `_verify_auth`) and module-global setter pattern. The
caller (backend) supplies `org_id` derived from the recruiter JWT upstream.
"""

import hmac

import structlog
from fastapi import APIRouter, Header, HTTPException

from src.config.settings import get_settings
from src.model.debrief import DebriefPacket, DebriefRequest
from src.service.debrief.debrief_service import DebriefService

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["debrief"])

_debrief_service: DebriefService | None = None


def set_debrief_service(service: DebriefService) -> None:
    global _debrief_service
    _debrief_service = service


def _get_debrief_service() -> DebriefService:
    if _debrief_service is None:
        raise HTTPException(status_code=503, detail="Debrief service not initialized")
    return _debrief_service


def _verify_auth(x_internal_secret: str | None) -> None:
    settings = get_settings()
    if not settings.auth.internal_secret:
        raise HTTPException(status_code=500, detail="Internal secret not configured")
    # Constant-time compare (matches backend's verify_internal_secret) so the
    # check doesn't leak the secret length/prefix via timing on a `!=`.
    if not hmac.compare_digest(x_internal_secret or "", settings.auth.internal_secret):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Internal-Secret")


@router.post("/debrief", response_model=DebriefPacket, status_code=200)
async def generate_debrief(
    request: DebriefRequest,
    x_internal_secret: str | None = Header(None),
) -> DebriefPacket:
    """Generate a comparative `DebriefPacket` for a candidate set under one role."""
    _verify_auth(x_internal_secret)
    service = _get_debrief_service()

    try:
        packet = await service.generate(
            org_id=request.org_id,
            requisition_id=request.requisition_id,
            candidate_ids=request.candidate_ids,
        )
    except Exception as e:
        logger.error(
            "debrief_generation_failed",
            org_id=request.org_id,
            requisition_id=request.requisition_id,
            error=str(e),
        )
        if hasattr(e, "status_code"):
            raise
        raise HTTPException(status_code=500, detail="Debrief generation failed")

    return packet
