import asyncio
import time

import structlog
from fastapi import APIRouter, Header, HTTPException, Response

from src.config.settings import get_settings
from src.model.ingestion import (
    IngestRequest,
    IngestDirectRequest,
    IngestResponse,
    OrgIngestRequest,
    OrgIngestResponse,
    OrgForcePublishRequest,
    ForcePublishJobCreatedResponse,
    ForcePublishJobStatusResponse,
    OrgIngestJobCreatedResponse,
    OrgIngestJobStatusResponse,
)
from src.service.event_router import EventRouter
from src.service.force_publish_job_service import ForcePublishJobService
from src.service.org_ingest_job_service import OrgIngestJobService
from src.service.org_ingestion_service import OrgIngestionService
from src.sync.brain_sync_cron import BrainSyncCron

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["ingestion"])

_event_router: EventRouter | None = None
_org_ingestion_service: OrgIngestionService | None = None
_brain_sync_cron: BrainSyncCron | None = None
_force_publish_job_service: ForcePublishJobService | None = None
_org_ingest_job_service: OrgIngestJobService | None = None


def set_event_router(event_router: EventRouter) -> None:
    global _event_router
    _event_router = event_router


def set_org_ingestion_service(service: OrgIngestionService) -> None:
    global _org_ingestion_service
    _org_ingestion_service = service


def set_brain_sync_cron(cron: BrainSyncCron) -> None:
    global _brain_sync_cron
    _brain_sync_cron = cron


def set_force_publish_job_service(service: ForcePublishJobService) -> None:
    global _force_publish_job_service
    _force_publish_job_service = service


def set_org_ingest_job_service(service: OrgIngestJobService) -> None:
    global _org_ingest_job_service
    _org_ingest_job_service = service


def _get_event_router() -> EventRouter:
    if _event_router is None:
        raise RuntimeError("EventRouter not initialized")
    return _event_router


def _get_org_ingestion_service() -> OrgIngestionService:
    if _org_ingestion_service is None:
        raise RuntimeError("OrgIngestionService not initialized")
    return _org_ingestion_service


def _get_brain_sync_cron() -> BrainSyncCron:
    if _brain_sync_cron is None:
        raise HTTPException(
            status_code=503,
            detail="Brain sync is disabled (sync.enabled=False or no sqs_queue_url) — force-publish unavailable",
        )
    return _brain_sync_cron


def _get_force_publish_job_service() -> ForcePublishJobService:
    if _force_publish_job_service is None:
        raise HTTPException(
            status_code=503,
            detail="Force-publish job service not initialized (brain sync disabled)",
        )
    return _force_publish_job_service


def _get_org_ingest_job_service() -> OrgIngestJobService:
    if _org_ingest_job_service is None:
        raise HTTPException(
            status_code=503,
            detail="Org ingest job service not initialized (no Supabase client)",
        )
    return _org_ingest_job_service


def _verify_auth(x_internal_secret: str | None) -> None:
    settings = get_settings()
    if not settings.auth.internal_secret:
        raise HTTPException(status_code=500, detail="Internal secret not configured")
    if x_internal_secret != settings.auth.internal_secret:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Internal-Secret")


@router.post("/ingest", response_model=IngestResponse, status_code=200)
async def ingest(
    request: IngestRequest,
    x_internal_secret: str | None = Header(None),
):
    _verify_auth(x_internal_secret)
    start = time.monotonic()
    event_router = _get_event_router()

    handler = event_router.get_handler(request.event_type)
    if handler is None:
        raise HTTPException(status_code=422, detail=f"Unknown event_type: {request.event_type}")

    try:
        result = await handler.handle(request.source_ref, request.org_id)
    except Exception as e:
        logger.error("ingestion_failed", event_type=request.event_type, error=str(e))
        if hasattr(e, "status_code"):
            raise
        raise HTTPException(status_code=500, detail=str(e))

    elapsed_ms = int((time.monotonic() - start) * 1000)

    return IngestResponse(
        status=result.status,
        event_type=request.event_type,
        nodes_created=result.nodes_created,
        edges_created=result.edges_created,
        processing_time_ms=elapsed_ms,
        errors=result.errors,
    )


@router.post("/ingest/direct", response_model=IngestResponse, status_code=200)
async def ingest_direct(
    request: IngestDirectRequest,
    x_internal_secret: str | None = Header(None),
):
    _verify_auth(x_internal_secret)
    start = time.monotonic()
    event_router = _get_event_router()

    handler = event_router.get_handler(request.event_type)
    if handler is None:
        raise HTTPException(status_code=422, detail=f"Unknown event_type: {request.event_type}")

    try:
        result = await handler.handle_direct(request.payload, request.org_id)
    except Exception as e:
        logger.error("direct_ingestion_failed", event_type=request.event_type, error=str(e))
        if hasattr(e, "status_code"):
            raise
        raise HTTPException(status_code=500, detail=str(e))

    elapsed_ms = int((time.monotonic() - start) * 1000)

    return IngestResponse(
        status=result.status,
        event_type=request.event_type,
        nodes_created=result.nodes_created,
        edges_created=result.edges_created,
        processing_time_ms=elapsed_ms,
        errors=result.errors,
    )


@router.post("/ingest/org", response_model=OrgIngestResponse, status_code=200)
async def ingest_org(
    request: OrgIngestRequest,
    x_internal_secret: str | None = Header(None),
):
    _verify_auth(x_internal_secret)
    start = time.monotonic()
    service = _get_org_ingestion_service()

    try:
        result = await service.ingest_org(request.org_id)
    except Exception as e:
        logger.error("org_ingestion_failed", org_id=request.org_id, error=str(e))
        if hasattr(e, "status_code"):
            raise
        raise HTTPException(status_code=500, detail=str(e))

    elapsed_ms = int((time.monotonic() - start) * 1000)

    return OrgIngestResponse(
        org_id=result["org_id"],
        total_nodes=result["total_nodes"],
        total_edges=result["total_edges"],
        total_errors=result["total_errors"],
        processing_time_ms=elapsed_ms,
        events=result["events"],
        errors=result["errors"],
    )


async def _run_force_publish_job(
    job_id: str,
    org_id: str,
    cron: BrainSyncCron,
    jobs: ForcePublishJobService,
) -> None:
    """Background task body. Runs the publish loop, reports per-batch progress,
    picks a terminal state based on what actually happened.

    Terminal status semantics:
        - no errors            → 'completed'
        - some published, some failed → 'partial'
        - zero published with errors   → 'failed' (SQS/Supabase outage, etc.)

    A previous version unconditionally called `mark_completed` even when every
    row failed, making outages indistinguishable from green runs to status
    pollers. Don't do that.
    """
    try:
        await jobs.mark_running(job_id)

        async def _on_progress(scanned: int, published: int, batches: int) -> None:
            await jobs.update_progress(
                job_id, scanned=scanned, published=published, batches=batches
            )

        result = await cron.publish_org_now(org_id, on_progress=_on_progress)
        scanned = result["scanned"]
        published = result["published"]
        batches = result["batches"]
        errors = result["errors"]

        if not errors:
            terminal = "completed"
            await jobs.mark_completed(
                job_id, scanned=scanned, published=published, batches=batches, errors=errors,
            )
        elif published > 0:
            terminal = "partial"
            await jobs.mark_partial(
                job_id, scanned=scanned, published=published, batches=batches, errors=errors,
            )
        else:
            terminal = "failed"
            summary = f"All {scanned} eligible rows failed to publish. First error: {errors[0]}"
            await jobs.mark_failed(job_id, summary)

        logger.info(
            "force_publish_job_terminal",
            job_id=job_id,
            org_id=org_id,
            terminal_status=terminal,
            scanned=scanned,
            published=published,
            batches=batches,
            errors=len(errors),
        )
    except Exception as e:
        logger.exception(
            "force_publish_job_failed", job_id=job_id, org_id=org_id, error=str(e)
        )
        try:
            await jobs.mark_failed(job_id, str(e))
        except Exception as mark_err:
            logger.error(
                "force_publish_mark_failed_errored",
                job_id=job_id,
                error=str(mark_err),
            )


@router.post(
    "/ingest/org/force-publish",
    response_model=ForcePublishJobCreatedResponse,
    status_code=202,
)
async def force_publish_org_events(
    request: OrgForcePublishRequest,
    response: Response,
    x_internal_secret: str | None = Header(None),
):
    """Kick off an async force-publish run for one org.

    Drains unpublished cortex_events for `org_id` to SQS now, bypassing the 48h
    settledness window the nightly cron uses. Downstream SQS consumer + handlers
    still do the actual graph ingestion. Capped at FORCE_PUBLISH_MAX_ROWS per
    run.

    Returns 202 with a job_id; poll GET /ingest/org/force-publish/{job_id} for
    status. If an in-flight job already exists for this org, returns 409 with
    the existing job_id (no duplicate spawn). Jobs that haven't reported progress
    in >5 min (likely a container restart) are auto-marked failed before the
    409 check runs, so a stuck previous run won't block a new attempt.
    """
    _verify_auth(x_internal_secret)
    cron = _get_brain_sync_cron()
    jobs = _get_force_publish_job_service()

    try:
        job_id, created = await jobs.create_or_409(request.org_id)
    except Exception as e:
        logger.error(
            "force_publish_job_create_failed", org_id=request.org_id, error=str(e)
        )
        raise HTTPException(status_code=500, detail=str(e))

    if not created:
        response.status_code = 409
        return ForcePublishJobCreatedResponse(
            job_id=job_id,
            org_id=request.org_id,
            status="running",
            already_running=True,
        )

    asyncio.create_task(_run_force_publish_job(job_id, request.org_id, cron, jobs))
    logger.info("force_publish_job_kicked_off", job_id=job_id, org_id=request.org_id)

    return ForcePublishJobCreatedResponse(
        job_id=job_id,
        org_id=request.org_id,
        status="pending",
        already_running=False,
    )


@router.get(
    "/ingest/org/force-publish/{job_id}",
    response_model=ForcePublishJobStatusResponse,
    status_code=200,
)
async def get_force_publish_job(
    job_id: str,
    x_internal_secret: str | None = Header(None),
):
    """Return current state of a force-publish job by id."""
    _verify_auth(x_internal_secret)
    jobs = _get_force_publish_job_service()

    try:
        row = await jobs.get(job_id)
    except Exception as e:
        logger.error("force_publish_job_get_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

    if row is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    return ForcePublishJobStatusResponse(
        job_id=str(row["id"]),
        org_id=str(row["org_id"]),
        status=row["status"],
        scanned=row.get("scanned", 0),
        published=row.get("published", 0),
        batches=row.get("batches", 0),
        errors=row.get("errors", []) or [],
        error_message=row.get("error_message"),
        started_at=row["started_at"],
        updated_at=row["updated_at"],
        completed_at=row.get("completed_at"),
    )


async def _run_org_ingest_job(
    job_id: str,
    org_id: str,
    service: OrgIngestionService,
    jobs: OrgIngestJobService,
) -> None:
    """Background task body for POST /ingest/org/async.

    Terminal status semantics (mirror force-publish):
        - no errors                    → 'completed'
        - some nodes+edges, some errs  → 'partial'
        - zero work + errors           → 'failed'
    """
    try:
        async def _events_total(n: int) -> None:
            await jobs.mark_running(job_id, events_total=n)

        async def _on_progress(**kwargs) -> None:
            await jobs.update_progress(job_id, **kwargs)

        result = await service.ingest_org(
            org_id,
            progress_callback=_on_progress,
            events_total_callback=_events_total,
        )

        nodes = result["total_nodes"]
        edges = result["total_edges"]
        errors_count = result["total_errors"]
        errors = result["errors"]
        event_counts = result["events"]
        events_processed = result.get("events_processed", 0)
        events_skipped = result.get("events_skipped", 0)

        if errors_count == 0:
            terminal = "completed"
            await jobs.mark_completed(
                job_id,
                events_processed=events_processed,
                events_skipped=events_skipped,
                nodes_created=nodes,
                edges_created=edges,
                errors_count=errors_count,
                event_counts=event_counts,
                errors=errors,
            )
        elif (nodes + edges) > 0:
            terminal = "partial"
            await jobs.mark_partial(
                job_id,
                events_processed=events_processed,
                events_skipped=events_skipped,
                nodes_created=nodes,
                edges_created=edges,
                errors_count=errors_count,
                event_counts=event_counts,
                errors=errors,
            )
        else:
            terminal = "failed"
            summary = f"All {events_processed + events_skipped} events produced zero writes. First error: {errors[0] if errors else 'unknown'}"
            await jobs.mark_failed(job_id, summary)

        logger.info(
            "org_ingest_job_terminal",
            job_id=job_id,
            org_id=org_id,
            terminal_status=terminal,
            nodes=nodes,
            edges=edges,
            errors=errors_count,
        )
    except Exception as e:
        logger.exception(
            "org_ingest_job_failed", job_id=job_id, org_id=org_id, error=str(e)
        )
        try:
            await jobs.mark_failed(job_id, str(e))
        except Exception as mark_err:
            logger.error(
                "org_ingest_mark_failed_errored",
                job_id=job_id,
                error=str(mark_err),
            )


@router.post(
    "/ingest/org/async",
    response_model=OrgIngestJobCreatedResponse,
    status_code=202,
)
async def ingest_org_async(
    request: OrgIngestRequest,
    response: Response,
    x_internal_secret: str | None = Header(None),
):
    """Kick off an async end-to-end org ingest. Returns 202 + job_id; poll
    GET /ingest/org/async/{job_id} for progress.

    Identical work to POST /ingest/org but runs in a background task so the
    HTTP client doesn't hold a connection open for 10+ minutes. Mirrors the
    /ingest/org/force-publish + status-poll pattern.

    If an in-flight job already exists for this org, returns 409 with the
    existing job_id (no duplicate spawn). Jobs that haven't reported progress
    in >5 min are auto-marked failed before the 409 check so a dead previous
    run won't block a new attempt.
    """
    _verify_auth(x_internal_secret)
    service = _get_org_ingestion_service()
    jobs = _get_org_ingest_job_service()

    try:
        job_id, created = await jobs.create_or_409(request.org_id)
    except Exception as e:
        logger.error(
            "org_ingest_job_create_failed", org_id=request.org_id, error=str(e)
        )
        raise HTTPException(status_code=500, detail=str(e))

    if not created:
        response.status_code = 409
        return OrgIngestJobCreatedResponse(
            job_id=job_id,
            org_id=request.org_id,
            status="running",
            already_running=True,
        )

    asyncio.create_task(_run_org_ingest_job(job_id, request.org_id, service, jobs))
    logger.info("org_ingest_job_kicked_off", job_id=job_id, org_id=request.org_id)

    return OrgIngestJobCreatedResponse(
        job_id=job_id,
        org_id=request.org_id,
        status="pending",
        already_running=False,
    )


@router.get(
    "/ingest/org/async/{job_id}",
    response_model=OrgIngestJobStatusResponse,
    status_code=200,
)
async def get_org_ingest_job(
    job_id: str,
    x_internal_secret: str | None = Header(None),
):
    """Return current state of an org ingest job by id."""
    _verify_auth(x_internal_secret)
    jobs = _get_org_ingest_job_service()

    try:
        row = await jobs.get(job_id)
    except Exception as e:
        logger.error("org_ingest_job_get_failed", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

    if row is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    return OrgIngestJobStatusResponse(
        job_id=str(row["id"]),
        org_id=str(row["org_id"]),
        status=row["status"],
        current_event_type=row.get("current_event_type"),
        events_total=row.get("events_total", 0),
        events_processed=row.get("events_processed", 0),
        events_skipped=row.get("events_skipped", 0),
        nodes_created=row.get("nodes_created", 0),
        edges_created=row.get("edges_created", 0),
        errors_count=row.get("errors_count", 0),
        event_counts=row.get("event_counts", {}) or {},
        errors=row.get("errors", []) or [],
        error_message=row.get("error_message"),
        started_at=row["started_at"],
        updated_at=row["updated_at"],
        completed_at=row.get("completed_at"),
    )
