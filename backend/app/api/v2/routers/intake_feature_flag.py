"""GET /intake/feature-flag — returns current user's org-level v2 intake enablement."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.services.intake_v2_feature_flag import is_intake_v2_enabled

router = APIRouter(prefix="/intake", tags=["v2/intake-feature-flag"])


class FeatureFlagResponse(BaseModel):
    intake_v2_enabled: bool


@router.get("/feature-flag", response_model=FeatureFlagResponse)
async def get_intake_v2_feature_flag(
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> FeatureFlagResponse:
    """Return whether v2 intake is enabled for the caller's organization."""
    enabled = await is_intake_v2_enabled(supabase, current.organization_id)
    return FeatureFlagResponse(intake_v2_enabled=enabled)
