"""Connect/verify/status/disconnect orchestration for ATS connections.

SECURITY: the FE-reported integrationDetails is never trusted — truth is
re-derived from Knit's integration.details for the CALLER's org before any
row is written (spec §4)."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel

from app.api.v2.core.dependencies import CurrentUserWithOrg
from app.api.v2.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.api.v2.core.rpc import call_rpc
from app.api.v2.services import ats_import_service
from app.api.v2.services.ats_import_service import ImportSummary
from app.integrations.ats.core.errors import AtsIntegrationError
from app.integrations.ats.unified_knit.auth import KnitPlatformApi
from app.integrations.ats.unified_knit.transport import get_knit_transport
from app.logging_config import get_logger

logger = get_logger(__name__)


class AtsConnectionStatus(BaseModel):
    connected: bool
    provider: str | None = None
    status: str | None = None
    connected_at: str | None = None
    connected_by_name: str | None = None
    import_summary: ImportSummary | None = None


def _platform() -> KnitPlatformApi:
    return KnitPlatformApi(get_knit_transport())


async def _org_name(supabase, org_id: str) -> str:
    result = await (
        supabase.table("organizations")
        .select("name")
        .eq("id", org_id)
        .limit(1)
        .execute_async()
    )
    return (result.data[0].get("name") if result.data else None) or org_id


async def _profile_name(supabase, user_id: str, fallback: str) -> str:
    result = await (
        supabase.table("profiles")
        .select("full_name")
        .eq("id", user_id)
        .limit(1)
        .execute_async()
    )
    return (result.data[0].get("full_name") if result.data else None) or fallback


async def create_auth_session(supabase, current: CurrentUserWithOrg) -> str:
    org_id = current.organization_id_str
    return await _platform().create_auth_session(
        origin_org_id=org_id,
        origin_org_name=await _org_name(supabase, org_id),
        origin_user_email=current.user.email,
        origin_user_name=await _profile_name(
            supabase, str(current.user.id), fallback=current.user.email
        ),
    )


async def complete_connection(
    supabase,
    current: CurrentUserWithOrg,
    *,
    integration_id: str,
    origin_org_id: str,
    app_id: str | None,
) -> AtsConnectionStatus:
    org_id = current.organization_id_str
    if origin_org_id != org_id:
        raise ForbiddenError("Integration belongs to a different organization")

    apps = await _platform().list_org_integrations(org_id)
    match = next((a for a in apps if a.integration_id == integration_id), None)
    if match is None or not match.is_active:
        raise ValidationError("Integration not found or inactive at Knit")
    if (match.category or "").upper() != "ATS":
        raise ValidationError("Integration is not an ATS integration")
    if app_id and match.app_id != app_id:
        logger.warning(
            "ats_connect_app_mismatch",
            extra={
                "event": "ats_connect_app_mismatch",
                "reported": app_id,
                "actual": match.app_id,
                "org_id": org_id,
            },
        )

    await call_rpc(
        supabase,
        "ats_connect",
        {
            "p_org_id": org_id,
            "p_provider": match.app_id,
            "p_integration_id": integration_id,
            "p_user_id": str(current.user.id),
        },
    )
    logger.info(
        "ats_connected",
        extra={"event": "ats_connected", "org_id": org_id, "provider": match.app_id},
    )
    status = await get_status(supabase, current)
    try:
        status.import_summary = await ats_import_service.run_import(
            supabase, org_id=org_id, user_id=str(current.user.id)
        )
    except Exception as exc:
        # The connection itself succeeded — a failed first import is re-runnable
        # via POST /integrations/ats/import. Never fail the connect for it.
        logger.error(
            "ats_connect_import_failed",
            extra={
                "event": "ats_connect_import_failed",
                "org_id": org_id,
                "error": str(exc),
            },
        )
        status.import_summary = None
    return status


async def _active_row(supabase, org_id: str) -> dict | None:
    result = await (
        supabase.table("ats_connections")
        .select("id, provider, status, connected_at, connected_by, knit_integration_id")
        .eq("organization_id", org_id)
        .eq("status", "active")
        .limit(1)
        .execute_async()
    )
    return result.data[0] if result.data else None


async def get_status(supabase, current: CurrentUserWithOrg) -> AtsConnectionStatus:
    row = await _active_row(supabase, current.organization_id_str)
    if not row:
        return AtsConnectionStatus(connected=False)
    name = None
    if row.get("connected_by"):
        name = await _profile_name(supabase, row["connected_by"], fallback="")
    return AtsConnectionStatus(
        connected=True,
        provider=row["provider"],
        status=row["status"],
        connected_at=row.get("connected_at"),
        connected_by_name=name or None,
    )


async def disconnect(supabase, current: CurrentUserWithOrg) -> None:
    org_id = current.organization_id_str
    row = await _active_row(supabase, org_id)
    if not row:
        raise NotFoundError("No ATS connected")
    try:
        await _platform().deactivate_integration(row["knit_integration_id"])
    except AtsIntegrationError as exc:
        # Best-effort: local disconnect proceeds; Knit-side cleanup can be manual.
        logger.warning(
            "knit_deactivate_failed",
            extra={
                "event": "knit_deactivate_failed",
                "org_id": org_id,
                "error": str(exc),
            },
        )
    now = datetime.now(timezone.utc).isoformat()
    await (
        supabase.table("ats_connections")
        .update({"status": "inactive", "deactivated_at": now, "updated_at": now})
        .eq("id", row["id"])
        .execute_async()
    )
    logger.info(
        "ats_disconnected", extra={"event": "ats_disconnected", "org_id": org_id}
    )
