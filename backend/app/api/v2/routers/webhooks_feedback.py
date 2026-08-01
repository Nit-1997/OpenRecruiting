import hmac
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from app.config import get_settings
from app.logging_config import get_logger, correlation_id_var
from app.services.feedback_notification_service import get_feedback_notification_service
from app.services.sqs_publisher import publish_event
from app.services.supabase import get_supabase_admin_client

router = APIRouter(prefix="/webhooks/feedback-complete", tags=["webhooks"])
logger = get_logger(__name__)


class FeedbackCompleteRequest(BaseModel):
    candidate_round_id: str


@router.post("")
async def handle_feedback_complete(
    request: FeedbackCompleteRequest,
    x_lambda_secret: str = Header(None, alias="X-Lambda-Secret"),
):
    correlation_id_var.set(f"cr:{request.candidate_round_id}")
    settings = get_settings()

    if not settings.LAMBDA_CALLBACK_SECRET:
        logger.warning("LAMBDA_CALLBACK_SECRET not configured, rejecting callback")
        raise HTTPException(status_code=500, detail="Callback secret not configured")

    if not hmac.compare_digest(x_lambda_secret or "", settings.LAMBDA_CALLBACK_SECRET):
        logger.warning(f"Invalid Lambda callback secret for round {request.candidate_round_id}")
        raise HTTPException(status_code=401, detail="Invalid callback secret")

    logger.info(f"Feedback complete callback received for {request.candidate_round_id}")

    notification_service = get_feedback_notification_service()

    try:
        result = await notification_service.send_happy_path_emails(request.candidate_round_id)
        logger.info(f"Happy path emails sent for {request.candidate_round_id}: {result}")

        supabase = get_supabase_admin_client()
        cr_result = await supabase.table("candidate_rounds") \
            .select("id, candidates!inner(requisition_id, requisitions!inner(organization_id))") \
            .eq("id", request.candidate_round_id) \
            .single() \
            .execute_async()
        if cr_result.data:
            org_id = cr_result.data.get("candidates", {}).get("requisitions", {}).get("organization_id")
            if org_id:
                await publish_event("feedback_complete", {
                    "candidate_round_id": request.candidate_round_id,
                    "organization_id": str(org_id),
                })

        return {
            "success": True,
            "candidate_round_id": request.candidate_round_id,
            "emails_sent": result,
        }
    except Exception as e:
        logger.error(f"Failed to send happy path emails for {request.candidate_round_id}: {e}")
        return {
            "success": False,
            "candidate_round_id": request.candidate_round_id,
            "error": str(e),
        }
