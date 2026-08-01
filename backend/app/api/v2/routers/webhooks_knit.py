"""Knit webhook receiver: verify signature, persist to the ledger, ack fast.

Processing happens asynchronously — the ats_sync drainer (phase 2) applies
pending ledger rows through adapters → policy RPCs. The receiver deliberately
does NOT touch processed_at; a row with processed_at IS NULL is the drainer's
work queue contract. Ack body follows Knit's expected response schema."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from app.api.v2.core.dependencies import Supabase
from app.config import get_settings
from app.integrations.ats.unified_knit.webhook.signature import verify_knit_signature
from app.logging_config import get_logger
from app.services.supabase import PostgrestError

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks/knit", tags=["v2/webhooks"])

_UNIQUE_VIOLATION = "23505"


@router.post("")
async def handle_knit_webhook(request: Request, supabase: Supabase) -> dict:
    body = await request.body()
    signature = request.headers.get("X-Knit-Signature")
    if not verify_knit_signature(body, signature, get_settings().KNIT_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = await request.json()
    event_id = payload.get("eventId")
    if not event_id:
        raise HTTPException(status_code=400, detail="Missing eventId")

    now = datetime.now(timezone.utc).isoformat()
    try:
        await (
            supabase.table("ats_webhook_events")
            .insert(
                {
                    "event_id": event_id,
                    "event_type": payload.get("eventType", ""),
                    "integration_id": request.headers.get("X-Knit-Integration-Id"),
                    "payload": payload,
                }
            )
            .execute_async()
        )
    except PostgrestError as exc:
        if exc.code == _UNIQUE_VIOLATION:
            logger.info(
                "knit_webhook_duplicate",
                extra={"event": "knit_webhook_duplicate", "event_id": event_id},
            )
            return {
                "success": True,
                "message": "duplicate",
                "processedAt": now,
                "eventId": event_id,
            }
        raise

    logger.info(
        "knit_webhook_received",
        extra={
            "event": "knit_webhook_received",
            "event_id": event_id,
            "event_type": payload.get("eventType", ""),
            "sync_data_type": payload.get("syncDataType"),
        },
    )
    return {
        "success": True,
        "message": "received",
        "processedAt": now,
        "eventId": event_id,
    }
