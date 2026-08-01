"""Role-level proactive screening suggestion (Cortex gap nudge).

  GET /roles/{requisition_id}/screening/suggestion

This is ROLE-level (not round-level), so it lives in its own router rather than
the per-round screening router (whose prefix is .../rounds/{round_id}/...). Gated
by `get_current_user_with_org`; the requisition is loaded org-scoped (404 on
cross-org / missing). Resolves org_id/org_name the same way the persona derive
route does, then delegates to the fail-safe suggestion service.
"""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.api.v2.core.exceptions import NotFoundError
from app.api.v2.schemas.screening import ScreeningSuggestionResponse
from app.api.v2.services.screening_suggestion_service import (
    ScreeningSuggestionService,
)


router = APIRouter(prefix="/roles/{requisition_id}/screening", tags=["v2/screening"])


async def _load_requisition_for_org(supabase, requisition_id: UUID, org_id: str) -> dict:
    """Fetch a requisition and verify it belongs to org_id. 404 on any mismatch."""
    result = await (
        supabase.table("requisitions")
        .select("id, organization_id, deleted_at, role_title")
        .eq("id", str(requisition_id))
        .is_null("deleted_at")
        .single()
        .execute_async()
    )
    if not result.data:
        raise NotFoundError("Role not found")
    if result.data.get("organization_id") != org_id:
        raise NotFoundError("Role not found")
    return result.data


async def _fetch_org_name(supabase, org_id: str) -> str:
    """Best-effort org display name for the Cortex reader; falls back to OpenRecruiting."""
    result = await (
        supabase.table("organizations")
        .select("name")
        .eq("id", org_id)
        .single()
        .execute_async()
    )
    if result.data and result.data.get("name"):
        return result.data["name"]
    return "OpenRecruiting"


@router.get("/suggestion", response_model=ScreeningSuggestionResponse)
async def get_screening_suggestion(
    requisition_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> ScreeningSuggestionResponse:
    """Proactive nudge: does Cortex show a recurring gap this role's screening
    could catch? Fail-safe — the service never raises, so a Cortex outage shows
    no banner rather than erroring the dashboard."""
    await _load_requisition_for_org(
        supabase, requisition_id, current.organization_id_str
    )
    org_id = current.organization_id_str
    org_name = await _fetch_org_name(supabase, org_id)

    result = await ScreeningSuggestionService(supabase).suggest(
        requisition_id=str(requisition_id), org_id=org_id, org_name=org_name
    )
    return ScreeningSuggestionResponse(**result)
