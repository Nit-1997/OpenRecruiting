"""HMAC verification for Knit webhooks: HMAC-SHA256 over the raw request
body, secret = the Knit API key, encoded Base64URLSafe WITHOUT padding,
delivered in X-Knit-Signature (verified against Knit docs 2026-06-11)."""

import base64
import hashlib
import hmac


def verify_knit_signature(body: bytes, signature: str | None, api_key: str) -> bool:
    if not api_key or not signature:
        return False
    digest = hmac.new(api_key.encode(), body, hashlib.sha256).digest()
    expected = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return hmac.compare_digest(expected, signature)
