"""POST /intake/parse-intent — turn a free-text role intent into form fields (LLM)."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
)
from app.api.v2.schemas.intake_parse_intent import ParseIntentRequest, ParseIntentResponse
from app.dependencies import get_anthropic_async_client
from app.services.intake.parse_intent_service import parse_role_intent

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/intake", tags=["v2/intake"])


@router.post("/parse-intent", response_model=ParseIntentResponse)
async def post_parse_intent(
    payload: ParseIntentRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    client=Depends(get_anthropic_async_client),
) -> ParseIntentResponse:
    fields = await parse_role_intent(client, payload.text)
    return ParseIntentResponse(**fields)
