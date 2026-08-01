"""Connect-time ATS job import + managed-sync kick-off.

Pages ats.job.list synchronously (jobs are few), maps each through the
requisitions adapter, applies via the ats_import_job RPC (the policy lives
there), tallies an explicit summary, then calls sync.start for ats_jobs +
ats_applications so Knit's managed sync takes over freshness."""

from __future__ import annotations

from pydantic import BaseModel

from app.api.v2.core.rpc import call_rpc
from app.integrations.ats.adapters.requisitions import to_requisition_fields
from app.integrations.ats.core.errors import (
    AtsIntegrationError,
    AtsNotConnectedError,
)
from app.integrations.ats.unified_knit.apis.jobs.api import KnitJobsApi
from app.integrations.ats.unified_knit.transport import get_knit_transport
from app.logging_config import get_logger

logger = get_logger(__name__)

_MAX_IMPORT_PAGES = 50
_SYNC_DATA_TYPES = ("ats_jobs", "ats_applications")


class ImportSummary(BaseModel):
    created: int = 0
    updated: int = 0
    flagged: int = 0
    skipped_closed: int = 0
    skipped_other: int = 0
    errors: int = 0
    sync_started: bool = False


async def _active_connection(supabase, org_id: str) -> dict:
    result = await (
        supabase.table("ats_connections")
        .select("id, provider, knit_integration_id")
        .eq("organization_id", org_id)
        .eq("status", "active")
        .limit(1)
        .execute_async()
    )
    if not result.data:
        raise AtsNotConnectedError(f"org {org_id} has no active ATS connection")
    return result.data[0]


async def start_managed_sync(integration_id: str) -> bool:
    """Kick Knit's managed sync. Fail-soft: the import already succeeded; a
    sync-kick failure is logged + reflected in the summary, re-kickable via
    POST /integrations/ats/import."""
    transport = get_knit_transport()
    try:
        for data_type in _SYNC_DATA_TYPES:
            await transport.request(
                "POST",
                "/sync.start",
                integration_id=integration_id,
                json={"dataType": data_type},
            )
        return True
    except AtsIntegrationError as exc:
        logger.warning(
            "ats_sync_start_failed",
            extra={"event": "ats_sync_start_failed", "error": str(exc)},
        )
        return False


async def run_import(
    supabase, *, org_id: str, user_id: str | None, include_closed: bool = False
) -> ImportSummary:
    connection = await _active_connection(supabase, org_id)
    jobs_api = KnitJobsApi(get_knit_transport(), connection["knit_integration_id"])
    summary = ImportSummary()

    page_token: str | None = None
    for _ in range(_MAX_IMPORT_PAGES):
        page = await jobs_api.list_jobs(page_token)
        for job in page.items:
            if job.status == "CLOSED" and not include_closed:
                summary.skipped_closed += 1
                continue
            try:
                result = await call_rpc(
                    supabase,
                    "ats_import_job",
                    {
                        "p_connection_id": connection["id"],
                        "p_org_id": org_id,
                        "p_provider": connection["provider"],
                        "p_ats_job_id": job.id,
                        "p_fields": to_requisition_fields(job),
                        "p_ats_status": job.status,
                        "p_user_id": user_id,
                    },
                )
                action = (result or {}).get("action")
                if action == "created":
                    summary.created += 1
                elif action == "updated":
                    summary.updated += 1
                elif action == "flagged":
                    summary.flagged += 1
                else:
                    summary.skipped_other += 1
            except Exception as exc:  # one bad job never kills the run
                summary.errors += 1
                logger.error(
                    "ats_import_job_failed",
                    extra={
                        "event": "ats_import_job_failed",
                        "ats_job_id": job.id,
                        "error": str(exc),
                    },
                )
        if not page.next_page_token:
            break
        page_token = page.next_page_token

    summary.sync_started = await start_managed_sync(
        connection["knit_integration_id"]
    )
    logger.info(
        "ats_import_summary",
        extra={
            "event": "ats_import_summary",
            "org_id": org_id,
            # nested: 'created' is a reserved LogRecord attribute
            "summary": summary.model_dump(),
        },
    )
    return summary
