import asyncio
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.logging_config import setup_logging, get_logger, request_id_var, correlation_id_var
from app.api.v2 import v2_router
from app.api.v2.core.error_handlers import register_v2_error_handlers
from app.services.intake_lock_cleanup import run_stale_lock_cleanup_loop
from app.services.supabase import get_supabase_admin_client

setup_logging()
logger = get_logger(__name__)


class RequestTimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in ("/", "/health"):
            return await call_next(request)
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "http_request",
            extra={
                "event": "http_request",
                "method": request.method,
                "path": path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "request_id": request_id_var.get(),
            },
        )
        return response


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Bind request_id + correlation_id ContextVars for the duration of the
    request so every log record (and every outbound HTTP call via the
    shared httpx clients) carries them.

    - `X-Request-ID` is a per-HTTP-request UUID. The UI generates and sends
      one per fetch; if missing, we mint one. Echoed in the response so the
      UI can attach it to its own error tracking.
    - `X-Correlation-ID` is an OPTIONAL multi-request grouping identifier
      the UI may send to tie together a multi-step recruiter action
      (e.g. "schedule round" = packet-load + schedule-call + recording-poll).
      Echoed in the response when present.
    """

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        cid = request.headers.get("X-Correlation-ID") or None
        # Also stash on request.state: the ContextVar is reset in this
        # middleware's finally block, which runs BEFORE the outermost
        # ServerErrorMiddleware-level catch-all Exception handler. That handler
        # reads request.state.request_id so the 500 envelope still carries the
        # id even after the ContextVar has been unwound.
        request.state.request_id = rid
        request.state.correlation_id = cid
        token_rid = request_id_var.set(rid)
        token_cid = correlation_id_var.set(cid)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            if cid:
                response.headers["X-Correlation-ID"] = cid
            return response
        finally:
            request_id_var.reset(token_rid)
            correlation_id_var.reset(token_cid)


@asynccontextmanager
async def lifespan(app: FastAPI):
    background_tasks: list[asyncio.Task] = []
    if get_settings().RUN_BACKGROUND_WORKERS:
        supabase_admin = get_supabase_admin_client()
        background_tasks.append(asyncio.create_task(run_stale_lock_cleanup_loop(supabase_admin)))
        logger.info("intake_lock_cleanup_task_scheduled")
        if get_settings().ATS_INTEGRATIONS_ENABLED:
            from app.services.ats_sync.drainer import run_ats_sync_drainer
            from app.services.ats_sync.interview_reconcile import (
                run_ats_interview_reconcile,
            )
            from app.services.ats_enrichment.worker import (
                run_ats_enrichment_worker,
            )

            background_tasks.append(
                asyncio.create_task(run_ats_sync_drainer(supabase_admin))
            )
            background_tasks.append(
                asyncio.create_task(run_ats_enrichment_worker(supabase_admin))
            )
            background_tasks.append(
                asyncio.create_task(run_ats_interview_reconcile(supabase_admin))
            )
            logger.info("ats_sync_drainer_scheduled")
            logger.info("ats_enrichment_worker_scheduled")
            logger.info("ats_interview_reconcile_scheduled")
    else:
        logger.info("background_workers_disabled")
    try:
        yield
    finally:
        for task in background_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if background_tasks:
            logger.info("background_tasks_stopped")
        from app.integrations.ats.unified_knit.transport import aclose_knit_transport

        await aclose_knit_transport()


app = FastAPI(
    title="OpenRecruiting Backend",
    description="OpenRecruiting Backend — layered architecture (PR 6 refactor). "
                "Spec: docs/superpowers/specs/2026-05-18-roles-detail-v2-api-design.md",
    version="2.0.0",
    lifespan=lifespan,
)

settings = get_settings()
origins = settings.CORS_ORIGINS.split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "If-Match",
        "X-Request-ID",
        "X-Correlation-ID",
    ],
    expose_headers=["X-Request-ID", "X-Correlation-ID"],
)

app.add_middleware(CorrelationIDMiddleware)
app.add_middleware(RequestTimingMiddleware)

register_v2_error_handlers(app)
app.include_router(v2_router)

# MCP OAuth discovery endpoints must live at the issuer ORIGIN (RFC 8414),
# so they are mounted at the app root, not under /api/v2.
from app.api.v2.routers.mcp_well_known import well_known_router  # noqa: E402

app.include_router(well_known_router)


@app.get("/", tags=["health"])
async def root():
    return {"message": "OpenRecruiting Backend is running", "service": "backend"}


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "healthy", "service": "backend"}
