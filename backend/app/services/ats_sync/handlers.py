"""Apply one ledger event. All writes go through SECURITY DEFINER RPCs (the
policy's single source of truth); this module only parses, maps, dispatches,
and translates results into an EventOutcome the drainer acts on."""

from __future__ import annotations

from dataclasses import dataclass

from app.api.v2.core.rpc import call_rpc
from app.integrations.ats.adapters.candidates import (
    CandidateSkip,
    to_candidate_fields,
    to_fast_lane_profile,
)
from app.integrations.ats.adapters.requisitions import to_requisition_fields
from app.integrations.ats.core.registry import get_ats_provider
from app.integrations.ats.unified_knit.adapters.events import (
    parse_application_event,
    parse_job_event,
)
from app.logging_config import get_logger
from app.services.ats_sync.interview_pull import pull_interviews_for_application

logger = get_logger(__name__)

RECORD_UPSERT_EVENTS = {"record.new", "record.modified"}
SYNC_EVENTS = {
    "sync.events.processed",
    "sync.events.allConsumed",
    "sync.heartbeat",
    "sync.failed",
}


@dataclass(slots=True)
class EventOutcome:
    status: str  # applied | applied_with_skip | orphaned | bookkeeping | ignored | failed
    detail: str | None = None


async def _connection_for_integration(
    supabase, integration_id: str | None
) -> dict | None:
    if not integration_id:
        return None
    result = await (
        supabase.table("ats_connections")
        .select("id, organization_id, provider, status")
        .eq("knit_integration_id", integration_id)
        .limit(1)
        .execute_async()
    )
    return result.data[0] if result.data else None


async def _trigger_interview_pull(supabase, org_id: str, application_id: str) -> None:
    """Targeted interview pull after an application upsert. Best-effort: a failure
    here (Ashby down, no native adapter, etc.) must never fail the application
    event — reconcile will catch the interviews on a later pass."""
    try:
        bundle = await get_ats_provider(supabase, org_id)
        await pull_interviews_for_application(
            supabase, bundle, org_id, application_id
        )
    except Exception as exc:  # noqa: BLE001 — best-effort; reconcile is the safety net
        logger.warning(
            "ats_interview_pull_failed",
            extra={
                "event": "ats_interview_pull_failed",
                "application_id": application_id,
                "error": str(exc),
            },
        )


async def apply_event(supabase, row: dict) -> EventOutcome:
    payload = row.get("payload") or {}
    event_type = payload.get("eventType", "")
    data_type = payload.get("syncDataType", "")

    if event_type in SYNC_EVENTS:
        logger.info(
            "ats_sync_bookkeeping",
            extra={
                "event": "ats_sync_bookkeeping",
                "event_type": event_type,
                "sync_data_type": data_type,
                "record_id": payload.get("recordId"),
            },
        )
        return EventOutcome("bookkeeping")

    if event_type not in RECORD_UPSERT_EVENTS and event_type != "record.deleted":
        return EventOutcome("ignored", f"unknown eventType {event_type!r}")

    connection = await _connection_for_integration(
        supabase, row.get("integration_id")
    )
    if connection is None:
        return EventOutcome("failed", "unknown integration id")
    org_id = connection["organization_id"]

    if event_type == "record.deleted":
        ats_type = "job" if data_type == "ats_jobs" else "application"
        record_id = payload.get("recordId") or ""
        if not record_id:
            return EventOutcome("failed", "record.deleted without recordId")
        await call_rpc(
            supabase,
            "ats_mark_deleted",
            {"p_org_id": org_id, "p_ats_type": ats_type, "p_ats_id": record_id},
        )
        return EventOutcome("applied")

    event_data = payload.get("eventData") or {}

    if data_type == "ats_jobs":
        job = parse_job_event(event_data)
        if job is None:
            return EventOutcome("failed", "unparseable job event")
        await call_rpc(
            supabase,
            "ats_import_job",
            {
                "p_connection_id": connection["id"],
                "p_org_id": org_id,
                "p_provider": connection["provider"],
                "p_ats_job_id": job.id,
                "p_fields": to_requisition_fields(job),
                "p_ats_status": job.status,
                "p_user_id": None,
            },
        )
        return EventOutcome("applied")

    if data_type == "ats_applications":
        application = parse_application_event(event_data)
        if application is None:
            return EventOutcome("failed", "unparseable application event")
        fields = to_candidate_fields(application)
        if isinstance(fields, CandidateSkip):
            logger.info(
                "ats_sync_candidate_skipped",
                extra={
                    "event": "ats_sync_candidate_skipped",
                    "reason": fields.reason,
                    "ats_application_id": fields.ats_application_id,
                },
            )
            return EventOutcome("applied_with_skip", fields.reason)
        result = await call_rpc(
            supabase,
            "ats_upsert_candidate",
            {
                "p_connection_id": connection["id"],
                "p_org_id": org_id,
                "p_provider": connection["provider"],
                "p_ats_application_id": application.id,
                "p_ats_candidate_id": application.candidate.id,
                "p_fields": fields,
                "p_ats_status": application.status,
                "p_stage_id": application.current_stage.id
                if application.current_stage
                else None,
                "p_stage_name": application.current_stage.name
                if application.current_stage
                else None,
                "p_profile": to_fast_lane_profile(application),
            },
        )
        if (result or {}).get("action") == "orphaned":
            return EventOutcome("orphaned", "job link not yet present")
        await _trigger_interview_pull(supabase, org_id, application.id)
        return EventOutcome("applied")

    return EventOutcome("ignored", f"unknown syncDataType {data_type!r}")
