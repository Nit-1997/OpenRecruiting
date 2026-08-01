import asyncio
import json
from datetime import datetime, timezone

from app.config import get_settings
from app.logging_config import get_logger
from app.services.jobs.invoker import INTAKE_TRANSCRIPT, get_invoker
from app.services.supabase import get_supabase_admin_client
from app.utils import parse_iso_datetime

logger = get_logger(__name__)

# Module-scope boto3 lambda client (sync, thread-safe). IntakeJobService is
# re-instantiated per call via get_intake_job_service(), so a per-instance
# lazy cache never helped — the client was rebuilt on every trigger. A
# process-wide singleton is correct here (NOT a loop-bound async resource).
_lambda_client = None


def _get_lambda_client():
    global _lambda_client
    if _lambda_client is None:
        import boto3
        settings = get_settings()
        _lambda_client = boto3.client(
            'lambda',
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )
    return _lambda_client


class IntakeJobServiceError(Exception):
    def __init__(self, message: str, error_code: str = None, details: dict = None):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)


class IntakeJobService:
    def __init__(self):
        settings = get_settings()
        self.function_arn = settings.INTAKE_LAMBDA_ARN
        self._lambda_client = None
        self._settings = settings

    @property
    def lambda_client(self):
        # Allow tests/instances to override via self._lambda_client; otherwise
        # fall back to the process-wide cached client.
        if self._lambda_client is None:
            return _get_lambda_client()
        return self._lambda_client

    async def can_process_intake(self, requisition_id: str) -> tuple[bool, str]:
        supabase = get_supabase_admin_client()

        req_result = await supabase.table("requisitions")\
            .select("id, intake_transcript, intake_processing_status, intake_processing_started_at")\
            .eq("id", requisition_id)\
            .is_null("deleted_at")\
            .execute_async()

        if not req_result.data:
            return False, "Requisition not found"

        req = req_result.data[0] if isinstance(req_result.data, list) else req_result.data

        if req.get("intake_processing_status") == "processing":
            started_at = req.get("intake_processing_started_at")
            if started_at:
                started = parse_iso_datetime(started_at)
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                if elapsed < 300:
                    return False, "Already processing"
                logger.warning(f"IntakeJob: Stale processing for {requisition_id} ({elapsed:.0f}s), allowing retry")
            else:
                return False, "Already processing"

        if not req.get("intake_transcript"):
            return False, "No intake transcript found"

        return True, "Ready to process"

    async def trigger_intake_processing(self, requisition_id: str) -> dict:
        supabase = get_supabase_admin_client()

        claimed = await supabase.rpc("claim_intake_processing", {
            "p_requisition_id": requisition_id,
        })
        if not claimed.data:
            logger.warning(f"IntakeJob: Cannot claim processing lock for {requisition_id}")
            return {
                'status': 'rejected',
                'reason': 'Already processing',
                'requisition_id': requisition_id,
            }

        return await self._trigger_via_lambda(requisition_id, supabase)

    async def _trigger_via_lambda(self, requisition_id: str, supabase) -> dict:
        from botocore.exceptions import ClientError

        try:
            logger.info(f"IntakeJob: Dispatching intake job for {requisition_id}")

            # Transport (local worker container vs AWS Lambda) is chosen by
            # JOB_INVOKER. A dispatch failure raises and is handled below.
            await get_invoker().invoke(INTAKE_TRANSCRIPT, {'requisition_id': requisition_id})

            logger.info(f"IntakeJob: Job accepted for {requisition_id}")
            return {
                'status': 'accepted',
                'requisition_id': requisition_id,
            }

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))

            logger.error(f"IntakeJob: Lambda invocation error: {error_code} - {error_message}")

            await supabase.table("requisitions")\
                .update({
                    "intake_processing_status": "failed",
                    "intake_processing_error": f"Lambda error: {error_code}"
                })\
                .eq("id", requisition_id)\
                .execute_async()

            raise IntakeJobServiceError(
                message=f"Lambda invocation failed: {error_message}",
                error_code=error_code,
                details=e.response
            )

        except Exception as e:
            logger.error(f"IntakeJob: Unexpected error: {e}")

            await supabase.table("requisitions")\
                .update({
                    "intake_processing_status": "failed",
                    "intake_processing_error": f"Unexpected error: {str(e)}"
                })\
                .eq("id", requisition_id)\
                .execute_async()

            raise IntakeJobServiceError(
                message=f"Failed to trigger intake job: {str(e)}",
                error_code="UNEXPECTED_ERROR"
            )

    async def get_processing_status(self, requisition_id: str) -> dict:
        supabase = get_supabase_admin_client()

        result = await supabase.table("requisitions")\
            .select("id, intake_processing_status, intake_processing_error, intake_processing_started_at, intake_processing_completed_at, intake_processing_stage, intake_summary")\
            .eq("id", requisition_id)\
            .execute_async()

        if not result.data:
            return {
                'found': False,
                'requisition_id': requisition_id,
            }

        req = result.data[0] if isinstance(result.data, list) else result.data
        return {
            'found': True,
            'requisition_id': requisition_id,
            'intake_processing_status': req.get('intake_processing_status'),
            'intake_processing_error': req.get('intake_processing_error'),
            'intake_processing_started_at': req.get('intake_processing_started_at'),
            'intake_processing_completed_at': req.get('intake_processing_completed_at'),
            'intake_processing_stage': req.get('intake_processing_stage'),
            'intake_summary': req.get('intake_summary'),
        }


def get_intake_job_service() -> IntakeJobService:
    return IntakeJobService()
