"""POST /assistant/route — classify a free-text message into a product flow (LLM)."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
)
from app.api.v2.schemas.assistant import AssistantRouteRequest, AssistantRouteResponse
from app.dependencies import get_llm_client
from app.services.assistant.route_intent_service import classify_route_intent

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/assistant", tags=["v2/assistant"])


@router.post("/route", response_model=AssistantRouteResponse)
async def post_assistant_route(
    payload: AssistantRouteRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    llm=Depends(get_llm_client),
) -> AssistantRouteResponse:
    intent = await classify_route_intent(llm, payload.text)
    return AssistantRouteResponse(intent=intent)
