import asyncio
import json
from typing import Optional
import boto3
from botocore.exceptions import ClientError
from datetime import datetime, timezone

from app.config import get_settings
from app.logging_config import get_logger
from app.services.jobs.invoker import FEEDBACK, get_invoker
from app.services.supabase import get_supabase_admin_client

logger = get_logger(__name__)

# Module-scope boto3 lambda client. boto3 clients are synchronous and
# thread-safe, so a process-wide singleton is correct (and far cheaper than
# the previous per-instance construction — FeedbackJobService is built fresh
# on every call via get_feedback_job_service()). This is NOT a loop-bound
# async resource, so the CLAUDE.md "never module-cache loop-bound async
# resources" rule does not apply.
_lambda_client = None


def _get_lambda_client():
    global _lambda_client
    if _lambda_client is None:
        settings = get_settings()
        _lambda_client = boto3.client(
            'lambda',
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )
    return _lambda_client


class FeedbackJobServiceError(Exception):
    def __init__(self, message: str, error_code: str = None, details: dict = None):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)


class FeedbackJobService:
    def __init__(self):
        settings = get_settings()
        self.lambda_client = _get_lambda_client()
        self.function_arn = settings.FEEDBACK_LAMBDA_ARN

    async def can_process_feedback(self, candidate_round_id: str) -> tuple[bool, str]:
        supabase = get_supabase_admin_client()

        cr_result = await supabase.table("candidate_rounds")\
            .select("id, round_id, processing_status")\
            .eq("id", candidate_round_id)\
            .execute_async()

        if not cr_result.data:
            return False, "Candidate round not found"

        cr = cr_result.data[0]

        if cr.get("processing_status") == "processing":
            return False, "Already processing"

        transcript_result = await supabase.table("transcripts")\
            .select("id, segments")\
            .eq("candidate_round_id", candidate_round_id)\
            .execute_async()

        if not transcript_result.data:
            return False, "No transcript found"

        transcript = transcript_result.data[0]
        segments = transcript.get("segments")
        if not segments or len(segments) == 0:
            return False, "No transcript segments found"

        round_id = cr.get("round_id")
        questions_result = await supabase.table("feedback_questions")\
            .select("id")\
            .eq("round_id", round_id)\
            .is_null("deleted_at")\
            .execute_async()

        if not questions_result.data or len(questions_result.data) == 0:
            return False, "No scorecard questions configured"

        return True, "Ready to process"

    async def trigger_feedback_processing(self, candidate_round_id: str, skip_prereq_check: bool = False) -> dict:
        supabase = get_supabase_admin_client()

        if not skip_prereq_check:
            can_process, reason = await self.can_process_feedback(candidate_round_id)
            if not can_process:
                logger.warning(f"FeedbackJob: Cannot process {candidate_round_id}: {reason}")
                return {
                    'status': 'rejected',
                    'reason': reason,
                    'candidate_round_id': candidate_round_id,
                }

        # Claim the round atomically before invoking so two triggers for the same
        # round never double-invoke the Lambda.
        #
        # The claim runs in the SECURITY DEFINER RPC claim_feedback_processing
        # (migration 111): it flips not-processing -> processing in one UPDATE and
        # returns whether THIS call won via ROW_COUNT. The previous in-Python CAS
        # gated on the PATCH `return=representation` body, but PostgREST re-applies
        # the request filter to that body — once the row is 'processing' the
        # self-excluding CAS filter drops it from the response, so a SUCCESSFUL
        # claim read back as empty, logged "CAS lost", and silently skipped the
        # Lambda (round wedged in 'processing' forever). ROW_COUNT is immune to it.
        #
        # skip_prereq_check=True is the documented force/override path (CLAUDE.md
        # "Lambda Code — Mandatory Rules" 8-9): fresh transcript data must override
        # any in-flight or wedged run, so it claims UNCONDITIONALLY and always
        # (re)invokes. The Lambda's writes are idempotent on candidate_round_id, so
        # a redundant invocation converges on the same final state. This is also
        # what lets a force-reprocess recover a round stuck in 'processing'.
        if skip_prereq_check:
            await supabase.table("candidate_rounds")\
                .update({
                    "processing_status": "processing",
                    "processing_started_at": datetime.now(timezone.utc).isoformat()
                })\
                .eq("id", candidate_round_id)\
                .execute_async()
        else:
            claimed = await supabase.rpc(
                "claim_feedback_processing", {"p_cr_id": candidate_round_id}
            )
            if not claimed.data:
                logger.info(
                    f"FeedbackJob: Skipping {candidate_round_id} — already processing "
                    f"(claim lost), not double-invoking"
                )
                return {
                    'status': 'skipped',
                    'reason': 'already_processing',
                    'candidate_round_id': candidate_round_id,
                }

        try:
            logger.info(f"FeedbackJob: Dispatching feedback job for {candidate_round_id}")

            # The transport (local worker container vs AWS Lambda) is chosen by
            # JOB_INVOKER. Either way this is fire-and-forget: the worker owns
            # the round's terminal state. A DISPATCH failure raises and is
            # handled below.
            await get_invoker().invoke(FEEDBACK, {'candidate_round_id': candidate_round_id})

            logger.info(f"FeedbackJob: Job accepted for {candidate_round_id}")
            return {
                'status': 'accepted',
                'candidate_round_id': candidate_round_id,
            }

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))

            logger.error(f"FeedbackJob: Lambda invocation error: {error_code} - {error_message}")

            await supabase.table("candidate_rounds")\
                .update({
                    "processing_status": "failed",
                    "processing_error": f"Lambda error: {error_code}"
                })\
                .eq("id", candidate_round_id)\
                .execute_async()

            raise FeedbackJobServiceError(
                message=f"Lambda invocation failed: {error_message}",
                error_code=error_code,
                details=e.response
            )

        except Exception as e:
            logger.error(f"FeedbackJob: Unexpected error: {e}")

            await supabase.table("candidate_rounds")\
                .update({
                    "processing_status": "failed",
                    "processing_error": f"Unexpected error: {str(e)}"
                })\
                .eq("id", candidate_round_id)\
                .execute_async()

            raise FeedbackJobServiceError(
                message=f"Failed to trigger feedback job: {str(e)}",
                error_code="UNEXPECTED_ERROR"
            )

    async def get_processing_status(self, candidate_round_id: str) -> dict:
        supabase = get_supabase_admin_client()

        result = await supabase.table("candidate_rounds")\
            .select("id, processing_status, processing_error, processing_started_at, processing_completed_at, rating, summary")\
            .eq("id", candidate_round_id)\
            .execute_async()

        if not result.data:
            return {
                'found': False,
                'candidate_round_id': candidate_round_id,
            }

        cr = result.data[0]
        return {
            'found': True,
            'candidate_round_id': candidate_round_id,
            'processing_status': cr.get('processing_status'),
            'processing_error': cr.get('processing_error'),
            'processing_started_at': cr.get('processing_started_at'),
            'processing_completed_at': cr.get('processing_completed_at'),
            'rating': cr.get('rating'),
            'summary': cr.get('summary'),
        }


def get_feedback_job_service() -> FeedbackJobService:
    return FeedbackJobService()
