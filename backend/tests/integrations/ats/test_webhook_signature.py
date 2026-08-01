"""Knit webhook HMAC: SHA256 over raw body, secret = API key, Base64URLSafe
no padding (verified against Knit docs 2026-06-11)."""

import base64
import hashlib
import hmac as hmac_lib

from app.integrations.ats.unified_knit.webhook.signature import verify_knit_signature


def sign(body: bytes, key: str) -> str:
    digest = hmac_lib.new(key.encode(), body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def test_valid_signature_passes():
    body = b'{"eventId":"e1"}'
    assert verify_knit_signature(body, sign(body, "test-knit-key"), "test-knit-key")


def test_signature_is_unpadded_base64url():
    body = b'{"eventId":"e1"}'
    padded = sign(body, "test-knit-key") + "=="
    assert not verify_knit_signature(body, padded, "test-knit-key")


def test_invalid_signature_fails():
    assert not verify_knit_signature(b"x", "nope", "test-knit-key")


def test_missing_signature_fails():
    assert not verify_knit_signature(b"x", None, "test-knit-key")


def test_empty_key_fails_closed():
    body = b"x"
    assert not verify_knit_signature(body, sign(body, ""), "")
