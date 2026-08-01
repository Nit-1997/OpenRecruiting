"""
HMAC verification for Recall.ai webhook signatures.

Recall uses Standard Webhooks signing (https://www.standardwebhooks.com/).
Each request carries three headers — `webhook-id`, `webhook-timestamp`,
`webhook-signature` — and the signed payload is `{id}.{timestamp}.{body}`.

Ported verbatim from `backend/v1/app/api/v1/webhooks/recall.py`
(lines 70-129) — the algorithm is dictated by Recall, no room for
variation. Tolerance is 5 minutes per the Standard Webhooks spec.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timezone

from fastapi import Request

from app.config import get_settings
from app.logging_config import get_logger


logger = get_logger(__name__)


# Standard Webhooks tolerance: requests outside this window are rejected
# even if the signature would otherwise verify. Prevents replay attacks.
_TIMESTAMP_TOLERANCE_SECONDS = 300


async def verify_webhook_signature(request: Request) -> bool:
    """Verify a Recall webhook request's signature.

    Returns True iff:
      - RECALL_WEBHOOK_SECRET is configured
      - webhook-id, webhook-timestamp, webhook-signature headers all present
      - timestamp within ±5 minutes of now
      - HMAC-SHA256(secret, "{id}.{ts}.{body}") matches one of the
        comma-separated `v1,<sig>` values in webhook-signature

    Side effects: reads the request body. Callers MUST then use
    `await request.json()` on the SAME request — FastAPI/Starlette caches
    the body so reading it twice is safe.
    """
    settings = get_settings()

    if not settings.RECALL_WEBHOOK_SECRET:
        logger.error("Webhook: RECALL_WEBHOOK_SECRET not configured, rejecting request")
        return False

    webhook_id = request.headers.get("webhook-id", "")
    webhook_timestamp = request.headers.get("webhook-timestamp", "")
    webhook_signature = request.headers.get("webhook-signature", "")

    if not webhook_signature:
        logger.warning("Webhook: No signature received")
        return False
    if not webhook_timestamp:
        logger.warning("Webhook: No timestamp received")
        return False

    try:
        timestamp_int = int(webhook_timestamp)
    except ValueError:
        logger.warning(f"Webhook: Invalid timestamp format: {webhook_timestamp}")
        return False

    current_time = int(datetime.now(timezone.utc).timestamp())
    if abs(current_time - timestamp_int) > _TIMESTAMP_TOLERANCE_SECONDS:
        logger.warning(
            f"Webhook: Timestamp out of tolerance: {timestamp_int}, current: {current_time}"
        )
        return False

    body = await request.body()
    signed_content = f"{webhook_id}.{webhook_timestamp}.{body.decode('utf-8')}"

    # Recall secrets are stored with the `whsec_` prefix; strip it before
    # base64-decoding.
    secret = settings.RECALL_WEBHOOK_SECRET
    if secret.startswith("whsec_"):
        secret = secret[len("whsec_"):]

    try:
        secret_bytes = base64.b64decode(secret)
    except Exception as e:
        logger.error(f"Webhook: secret is not valid base64: {e}")
        return False

    expected_sig = hmac.new(
        secret_bytes,
        signed_content.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected_b64 = base64.b64encode(expected_sig).decode("utf-8")

    # webhook-signature may carry multiple space-separated values, each
    # prefixed with a version tag (`v1,<sig>`). Accept the first match.
    for sig in webhook_signature.split(" "):
        if sig.startswith("v1,"):
            received_sig = sig[3:]
            if hmac.compare_digest(received_sig, expected_b64):
                logger.debug("Webhook: signature verified")
                return True

    logger.warning("Webhook: signature mismatch")
    return False
