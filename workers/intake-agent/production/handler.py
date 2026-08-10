"""AWS Lambda handler — intake-agent-v2-worker.

Input payload: {"session_id": "<uuid>"}
Reads:         intake_sessions row by session_id
Writes:        rounds, feedback_questions, intake_sessions.interview_plan
Publishes:     SQS event intake_v2_completed

Adheres to CLAUDE.md "Lambda Code — Mandatory Rules":
- Fresh event loop per invocation
- All async resources closed inside the entry coroutine's finally:
- Warm-container safe (two invocations on the same Python process must succeed)
"""
from __future__ import annotations

import asyncio
import time

import structlog

from src.clients.llm import LLMGatewayClient
from src.clients.supabase import SupabaseClient, close_async_http_client
from src.config import get_settings
from src.logging import configure_logging, get_logger
from src.pipeline import IntakePipelineV2

settings = get_settings()
configure_logging(level=settings.log_level, format=settings.log_format)
logger = get_logger(__name__)


def handler(event, context):
    session_id = event.get("session_id")
    if not session_id:
        logger.error("missing_session_id")
        return {"statusCode": 400, "error": "session_id required"}

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        session_id=session_id,
        aws_request_id=getattr(context, "aws_request_id", None),
        service="intake-agent-v2",
    )
    logger.info("worker_start")

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(process_intake_v2(session_id))
    finally:
        loop.close()

    return {
        "statusCode": 200,
        "session_id": session_id,
        "status": result,
    }


async def process_intake_v2(session_id: str) -> str:
    start_time = time.monotonic()
    supabase = SupabaseClient()

    try:
        role_context = await supabase.get_session_context(session_id)
        async with LLMGatewayClient() as llm:
            pipeline = IntakePipelineV2(llm=llm, supabase=supabase, session_id=session_id)
            await pipeline.run(role_context)
        logger.info(
            "worker_complete",
            duration_ms=int((time.monotonic() - start_time) * 1000),
        )
        return "completed"
    except Exception as e:
        # exc_info=True captures the full traceback in CloudWatch. Without it a bare
        # str(e) like "0" (e.g. a KeyError(0)) is undiagnosable — which is exactly how
        # a real production failure stayed invisible. Persist a typed message too, so
        # process_error carries "KeyError: 0" rather than a contextless "0".
        detail = f"{type(e).__name__}: {e}"
        logger.error(
            "worker_failed",
            error=detail,
            duration_ms=int((time.monotonic() - start_time) * 1000),
            exc_info=True,
        )
        try:
            await supabase.mark_session_failed(session_id, detail)
        except Exception as patch_err:
            logger.warning("mark_session_failed_failed", error=str(patch_err))
        return "failed"
    finally:
        # Mandatory: close async clients inside the live loop
        try:
            await close_async_http_client()
        except Exception as close_err:
            logger.warning("close_failed", error=str(close_err))
