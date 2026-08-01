"""Characterization tests for recall_webhook.signature.verify_webhook_signature."""

import base64
import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.recall_webhook import signature


class _FakeRequest:
    def __init__(self, headers: dict, body: bytes):
        self.headers = headers
        self._body = body

    async def body(self):
        return self._body


def _settings(secret="whsec_" + base64.b64encode(b"supersecretkey").decode()):
    return SimpleNamespace(RECALL_WEBHOOK_SECRET=secret)


def _sign(secret_b64_no_prefix: str, wid: str, ts: str, body: bytes) -> str:
    secret_bytes = base64.b64decode(secret_b64_no_prefix)
    signed = f"{wid}.{ts}.{body.decode()}".encode()
    digest = hmac.new(secret_bytes, signed, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


def _now_ts():
    from datetime import datetime, timezone
    return str(int(datetime.now(timezone.utc).timestamp()))


@pytest.mark.asyncio
async def test_no_secret_rejected():
    req = _FakeRequest({}, b"{}")
    with patch.object(signature, "get_settings", lambda: _settings(secret="")):
        assert await signature.verify_webhook_signature(req) is False


@pytest.mark.asyncio
async def test_missing_signature_header():
    req = _FakeRequest({"webhook-timestamp": _now_ts()}, b"{}")
    with patch.object(signature, "get_settings", _settings):
        assert await signature.verify_webhook_signature(req) is False


@pytest.mark.asyncio
async def test_missing_timestamp_header():
    req = _FakeRequest({"webhook-signature": "v1,abc"}, b"{}")
    with patch.object(signature, "get_settings", _settings):
        assert await signature.verify_webhook_signature(req) is False


@pytest.mark.asyncio
async def test_invalid_timestamp_format():
    req = _FakeRequest({"webhook-signature": "v1,abc", "webhook-timestamp": "notanint"}, b"{}")
    with patch.object(signature, "get_settings", _settings):
        assert await signature.verify_webhook_signature(req) is False


@pytest.mark.asyncio
async def test_timestamp_out_of_tolerance():
    req = _FakeRequest({"webhook-signature": "v1,abc", "webhook-timestamp": "1000000000"}, b"{}")
    with patch.object(signature, "get_settings", _settings):
        assert await signature.verify_webhook_signature(req) is False


@pytest.mark.asyncio
async def test_secret_not_base64_rejected():
    req = _FakeRequest(
        {"webhook-signature": "v1,abc", "webhook-timestamp": _now_ts(), "webhook-id": "id1"},
        b"{}",
    )
    with patch.object(signature, "get_settings", lambda: _settings(secret="whsec_@@@not base64@@@")):
        assert await signature.verify_webhook_signature(req) is False


@pytest.mark.asyncio
async def test_valid_signature_accepted():
    raw_secret_b64 = base64.b64encode(b"supersecretkey").decode()
    ts = _now_ts()
    wid = "msg_1"
    body = b'{"event":"x"}'
    sig = _sign(raw_secret_b64, wid, ts, body)
    req = _FakeRequest(
        {"webhook-id": wid, "webhook-timestamp": ts, "webhook-signature": sig},
        body,
    )
    with patch.object(signature, "get_settings", lambda: _settings(secret="whsec_" + raw_secret_b64)):
        assert await signature.verify_webhook_signature(req) is True


@pytest.mark.asyncio
async def test_signature_mismatch_rejected():
    raw_secret_b64 = base64.b64encode(b"supersecretkey").decode()
    ts = _now_ts()
    req = _FakeRequest(
        {"webhook-id": "id1", "webhook-timestamp": ts, "webhook-signature": "v1,wrongsig=="},
        b'{"event":"x"}',
    )
    with patch.object(signature, "get_settings", lambda: _settings(secret="whsec_" + raw_secret_b64)):
        assert await signature.verify_webhook_signature(req) is False
