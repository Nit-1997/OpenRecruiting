"""ATS integration routes (Knit-backed).

Mounted under /api/v2/integrations/ats:
  POST   /session       Auth-session token for the embedded knit-auth component
  POST   /connections   Verify + persist a completed Knit integration
  GET    /status        Active connection status for the caller's org
  DELETE /connection    Disconnect (Knit deactivation best-effort + local row)
  GET    /jobs, /jobs/{job_id}                 Read-only browse (canonical DTOs)
  GET    /candidates                           Structured search
  GET    /applications, /applications/{id}     Read-only browse

Spec: docs/superpowers/specs/2026-06-11-knit-ats-phase1-connect-design.md
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.v2.core.dependencies import CurrentUserOrg, Supabase
from app.api.v2.core.exceptions import NotFoundError, ValidationError
from app.api.v2.core.rpc import call_rpc
from app.api.v2.services import ats_connection_service, ats_import_service
from app.api.v2.services.ats_connection_service import AtsConnectionStatus
from app.api.v2.services.ats_import_service import ImportSummary
from app.config import get_settings
from app.integrations.ats.core.models import (
    AtsApplication,
    AtsCandidate,
    AtsJob,
    CandidateSearchCriteria,
    Page,
)
from app.integrations.ats.core.registry import get_ats_provider
from app.integrations.ats.unified_knit.apis.candidates.api import KnitCandidatesApi
from app.integrations.ats.unified_knit.transport import get_knit_transport

router = APIRouter(prefix="/integrations/ats", tags=["v2/integrations/ats"])


def require_ats_enabled() -> None:
    """Feature gate: with the flag off the whole surface is a 404 (the
    feature does not exist for the deployment)."""
    if not get_settings().ATS_INTEGRATIONS_ENABLED:
        raise NotFoundError("ATS integrations are not enabled")


class AtsSessionResponse(BaseModel):
    token: str


class KnitIntegrationDetailsIn(BaseModel):
    """Verbatim integrationDetails payload from the knit-auth onFinish event."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    integration_id: str = Field(alias="integrationId")
    app_id: str | None = Field(alias="appId", default=None)
    category_id: str | None = Field(alias="categoryId", default=None)
    origin_org_id: str = Field(alias="originOrgId")
    success: bool = True


class AtsDisconnectResponse(BaseModel):
    disconnected: bool


@router.post(
    "/session",
    response_model=AtsSessionResponse,
    dependencies=[Depends(require_ats_enabled)],
)
async def create_session(
    current: CurrentUserOrg, supabase: Supabase
) -> AtsSessionResponse:
    token = await ats_connection_service.create_auth_session(supabase, current)
    return AtsSessionResponse(token=token)


@router.post(
    "/connections",
    response_model=AtsConnectionStatus,
    dependencies=[Depends(require_ats_enabled)],
)
async def complete_connection(
    payload: KnitIntegrationDetailsIn, current: CurrentUserOrg, supabase: Supabase
) -> AtsConnectionStatus:
    if not payload.success:
        raise ValidationError("Integration was not completed successfully")
    return await ats_connection_service.complete_connection(
        supabase,
        current,
        integration_id=payload.integration_id,
        origin_org_id=payload.origin_org_id,
        app_id=payload.app_id,
    )


@router.get(
    "/status",
    response_model=AtsConnectionStatus,
    dependencies=[Depends(require_ats_enabled)],
)
async def get_status(
    current: CurrentUserOrg, supabase: Supabase
) -> AtsConnectionStatus:
    return await ats_connection_service.get_status(supabase, current)


@router.delete(
    "/connection",
    response_model=AtsDisconnectResponse,
    dependencies=[Depends(require_ats_enabled)],
)
async def disconnect(
    current: CurrentUserOrg, supabase: Supabase
) -> AtsDisconnectResponse:
    await ats_connection_service.disconnect(supabase, current)
    return AtsDisconnectResponse(disconnected=True)


@router.post(
    "/import",
    response_model=ImportSummary,
    dependencies=[Depends(require_ats_enabled)],
)
async def run_ats_import(
    current: CurrentUserOrg,
    supabase: Supabase,
    include_closed: bool = Query(default=False),
) -> ImportSummary:
    return await ats_import_service.run_import(
        supabase,
        org_id=current.organization_id_str,
        user_id=str(current.user.id),
        include_closed=include_closed,
    )


class AtsSyncStatusResponse(BaseModel):
    pending_events: int
    failed_events: int
    last_event_at: str | None = None


@router.get(
    "/sync-status",
    response_model=AtsSyncStatusResponse,
    dependencies=[Depends(require_ats_enabled)],
)
async def get_sync_status(
    current: CurrentUserOrg, supabase: Supabase
) -> AtsSyncStatusResponse:
    pending = await (
        supabase.table("ats_webhook_events")
        .select("event_id")
        .is_null("processed_at")
        .count_async()
    )
    # Parked rows carry retry_count == ATS_SYNC_MAX_RETRIES exactly (the
    # drainer marks them processed at that point, so the count never moves).
    failed = await (
        supabase.table("ats_webhook_events")
        .select("event_id")
        .eq("retry_count", str(get_settings().ATS_SYNC_MAX_RETRIES))
        .count_async()
    )
    latest = await (
        supabase.table("ats_webhook_events")
        .select("received_at")
        .order("received_at", desc=True)
        .limit(1)
        .execute_async()
    )
    last_event_at = latest.data[0]["received_at"] if latest.data else None
    return AtsSyncStatusResponse(
        pending_events=pending, failed_events=failed, last_event_at=last_event_at
    )


class AtsRequisitionSyncResponse(BaseModel):
    linked: bool
    provider: str | None = None
    ats_status: str | None = None
    ats_dirty: bool = False
    ats_deleted: bool = False
    pending_changes: dict | None = None


@router.get(
    "/requisitions/{requisition_id}/sync",
    response_model=AtsRequisitionSyncResponse,
    dependencies=[Depends(require_ats_enabled)],
)
async def get_requisition_sync(
    requisition_id: UUID, current: CurrentUserOrg, supabase: Supabase
) -> AtsRequisitionSyncResponse:
    result = await (
        supabase.table("ats_entity_links")
        .select("provider, ats_status, ats_dirty, ats_deleted, ats_dirty_payload")
        .eq("organization_id", current.organization_id_str)
        .eq("native_type", "requisition")
        .eq("native_id", str(requisition_id))
        .limit(1)
        .execute_async()
    )
    if not result.data:
        return AtsRequisitionSyncResponse(linked=False)
    link = result.data[0]
    pending = link.get("ats_dirty_payload") or None
    if pending:
        pending = {k: v for k, v in pending.items() if k != "ats_job_id"}
    return AtsRequisitionSyncResponse(
        linked=True,
        provider=link["provider"],
        ats_status=link.get("ats_status"),
        ats_dirty=bool(link.get("ats_dirty")),
        ats_deleted=bool(link.get("ats_deleted")),
        pending_changes=pending,
    )


@router.post(
    "/requisitions/{requisition_id}/apply-update",
    dependencies=[Depends(require_ats_enabled)],
)
async def apply_requisition_update(
    requisition_id: UUID, current: CurrentUserOrg, supabase: Supabase
) -> dict:
    result = await call_rpc(
        supabase,
        "ats_apply_dirty_update",
        {
            "p_org_id": current.organization_id_str,
            "p_requisition_id": str(requisition_id),
        },
    )
    return {"applied": (result or {}).get("action") == "applied"}


@router.post(
    "/requisitions/{requisition_id}/dismiss-update",
    dependencies=[Depends(require_ats_enabled)],
)
async def dismiss_requisition_update(
    requisition_id: UUID, current: CurrentUserOrg, supabase: Supabase
) -> dict:
    await (
        supabase.table("ats_entity_links")
        .update({"ats_dirty": False, "ats_dirty_payload": None})
        .eq("organization_id", current.organization_id_str)
        .eq("native_type", "requisition")
        .eq("native_id", str(requisition_id))
        .execute_async()
    )
    return {"dismissed": True}


@router.get(
    "/jobs",
    response_model=Page[AtsJob],
    dependencies=[Depends(require_ats_enabled)],
)
async def list_jobs(
    current: CurrentUserOrg,
    supabase: Supabase,
    page_token: str | None = Query(default=None),
) -> Page[AtsJob]:
    bundle = await get_ats_provider(supabase, current.organization_id_str)
    return await bundle.jobs.list_jobs(page_token)


@router.get(
    "/jobs/{job_id}",
    response_model=AtsJob,
    dependencies=[Depends(require_ats_enabled)],
)
async def get_job(job_id: str, current: CurrentUserOrg, supabase: Supabase) -> AtsJob:
    bundle = await get_ats_provider(supabase, current.organization_id_str)
    return await bundle.jobs.get_job(job_id)


@router.get(
    "/candidates",
    response_model=list[AtsCandidate],
    dependencies=[Depends(require_ats_enabled)],
)
async def search_candidates(
    current: CurrentUserOrg,
    supabase: Supabase,
    first_name: str | None = Query(default=None),
    last_name: str | None = Query(default=None),
    email: str | None = Query(default=None),
    phone: str | None = Query(default=None),
) -> list[AtsCandidate]:
    criteria = CandidateSearchCriteria(
        first_name=first_name, last_name=last_name, email=email, phone=phone
    )
    if criteria.is_empty():
        raise ValidationError(
            "Provide at least one of: first_name, last_name, email, phone"
        )
    bundle = await get_ats_provider(supabase, current.organization_id_str)
    # Browse/preview uses the UNIFIED candidates API (enumeration cursor) for every
    # provider. Native adapters (bundle.candidates) are reserved for the enrichment
    # pipeline's rich get_application and intentionally don't implement search/list.
    candidates = KnitCandidatesApi(get_knit_transport(), bundle.knit_integration_id)
    return await candidates.search_candidates(criteria)


@router.get(
    "/applications",
    response_model=Page[AtsApplication],
    dependencies=[Depends(require_ats_enabled)],
)
async def list_applications(
    current: CurrentUserOrg,
    supabase: Supabase,
    page_token: str | None = Query(default=None),
) -> Page[AtsApplication]:
    bundle = await get_ats_provider(supabase, current.organization_id_str)
    candidates = KnitCandidatesApi(get_knit_transport(), bundle.knit_integration_id)
    return await candidates.list_applications(page_token)


@router.get(
    "/applications/{application_id}",
    response_model=AtsApplication,
    dependencies=[Depends(require_ats_enabled)],
)
async def get_application(
    application_id: str,
    current: CurrentUserOrg,
    supabase: Supabase,
    candidate_id: str = Query(...),
) -> AtsApplication:
    bundle = await get_ats_provider(supabase, current.organization_id_str)
    candidates = KnitCandidatesApi(get_knit_transport(), bundle.knit_integration_id)
    return await candidates.get_application(application_id, candidate_id)
