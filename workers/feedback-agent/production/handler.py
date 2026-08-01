import asyncio
import time

import httpx
import structlog

from src.clients import supabase as supabase_module
from src.clients.supabase import get_supabase_client
from src.config import get_settings
from src.jobs.processor import JobProcessor
from src.jobs.result_transformer import transform_to_feedback_output
from src.logging import configure_logging, get_logger
from src.runner import run_pipeline_for_inputs
from src.services import FeedbackOrchestrator

settings = get_settings()
configure_logging(level=settings.log_level, format=settings.log_format)
logger = get_logger(__name__)


def handler(event, context):
    candidate_round_id = event.get("candidate_round_id")

    if not candidate_round_id:
        logger.error("missing_candidate_round_id")
        return {"statusCode": 400, "error": "candidate_round_id required"}

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        candidate_round_id=candidate_round_id,
        aws_request_id=getattr(context, "aws_request_id", None),
        service="feedback-agent",
    )

    logger.info(
        "worker_start",
        backend_url=settings.backend_url[:50] if settings.backend_url else "EMPTY",
        has_callback_secret=bool(settings.lambda_callback_secret),
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(process_feedback(candidate_round_id))
    finally:
        loop.close()

    return {
        "statusCode": 200,
        "candidate_round_id": candidate_round_id,
        "status": result,
    }


async def process_feedback(candidate_round_id: str) -> str:
    start_time = time.monotonic()
    supabase = get_supabase_client()
    processor = JobProcessor(supabase=supabase)

    try:
        await supabase.update_processing_status(candidate_round_id, "processing")

        feedback_source = await supabase.get_feedback_source(candidate_round_id)

        questions, questions_map = await supabase.get_scorecard_questions(
            candidate_round_id
        )
        if not questions:
            raise ValueError("No scorecard questions found")

        role_context = await supabase.get_role_context(candidate_round_id)

        # Build the transcript dict in the shape src/runner.py expects.
        if feedback_source["source"] == "scorecard":
            segments = None
            if feedback_source.get("has_interview_transcript"):
                segments, _ = await supabase.get_transcript_data(candidate_round_id)
            transcript = {
                "segments": segments or [],
                "feedback_transcript": "",
                "feedback_start_timestamp": None,
            }
            logger.info(
                "using_scorecard_path",
                has_interview_segments=segments is not None,
                interview_segments_count=len(segments) if segments else 0,
            )
        else:
            if feedback_source["source"] == "none":
                logger.warning("no_feedback_source_trying_segments")
            segments, feedback_start_ts = await supabase.get_transcript_data(
                candidate_round_id
            )
            if not segments:
                raise ValueError("No transcript segments found and no scorecard transcript available")
            transcript = {
                "segments": segments,
                "feedback_transcript": "",
                "feedback_start_timestamp": feedback_start_ts,
            }

        result = await run_pipeline_for_inputs(
            feedback_source=feedback_source,
            questions=questions,
            role_context=role_context,
            transcript=transcript,
            processor=processor,
        )

        judge_result = result.get("judge_result", {})
        summary_result = result.get("summary_result", {})
        feedback_output = transform_to_feedback_output(judge_result, summary_result)

        has_content = bool(
            feedback_output.get("feedback_questions")
            or feedback_output.get("round_summary")
            or feedback_output.get("round_rating")
        )

        if not has_content:
            logger.warning(
                "empty_pipeline_results",
                round_rating=feedback_output.get("round_rating"),
            )
            await supabase.update_processing_status(
                candidate_round_id, "failed",
                error="Insufficient feedback content to generate results"
            )
            return "failed"

        await supabase.save_feedback_results(
            candidate_round_id, feedback_output, questions_map
        )

        await supabase.update_processing_status(candidate_round_id, "completed")

        await notify_feedback_complete(candidate_round_id)

        logger.info("worker_complete", duration_ms=int((time.monotonic() - start_time) * 1000))
        return "completed"

    except Exception as e:
        logger.error("worker_failed", error=str(e), duration_ms=int((time.monotonic() - start_time) * 1000))
        await supabase.update_processing_status(
            candidate_round_id, "failed", error=str(e)
        )
        return "failed"
    finally:
        client = supabase_module._async_client
        if client is not None:
            try:
                await client.aclose()
            except Exception as close_err:
                logger.warning("async_client_close_failed", error=str(close_err))
            supabase_module._async_client = None


async def notify_feedback_complete(candidate_round_id: str) -> None:
    """Call backend to trigger notification emails after feedback completes."""
    backend_url = settings.backend_url.strip() if settings.backend_url else ""
    callback_secret = settings.lambda_callback_secret

    if not backend_url or not callback_secret:
        logger.warning(
            "notification_callback_skipped",
            reason="backend callback not configured",
            backend_url_len=len(settings.backend_url) if settings.backend_url else 0,
            backend_url_repr=repr(settings.backend_url[:80]) if settings.backend_url else "None",
        )
        return

    callback_url = f"{backend_url}/api/v2/webhooks/feedback-complete"
    logger.info(
        "notification_callback_attempt",
        callback_url=callback_url,
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                callback_url,
                json={"candidate_round_id": candidate_round_id},
                headers={"X-Lambda-Secret": callback_secret}
            )
            if response.status_code == 200:
                logger.info("notification_callback_sent")
            else:
                logger.warning(
                    "notification_callback_failed",
                    status=response.status_code,
                    body=response.text[:200]
                )
        except Exception as e:
            logger.error(
                "notification_callback_error",
                callback_url=callback_url,
                error=str(e),
            )
