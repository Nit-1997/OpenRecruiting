"""Tests for voice_v2_client.request_voice_offer — the HTTP shim that posts a
WebRTC offer to voice-agent and returns its answer (or raises on a
rejection / HTTP error)."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.voice_v2_client import request_voice_offer


def _mock_async_client(post_response=None, post_side_effect=None):
    """Patch httpx.AsyncClient so the `async with` context yields a client whose
    .post returns/raises as configured."""
    cm = patch("app.services.voice_v2_client.httpx.AsyncClient")
    mock_ac = cm.start()
    instance = mock_ac.return_value.__aenter__.return_value
    if post_side_effect is not None:
        instance.post = AsyncMock(side_effect=post_side_effect)
    else:
        instance.post = AsyncMock(return_value=post_response)
    return cm, instance


async def test_request_voice_offer_returns_answer():
    resp = MagicMock(
        raise_for_status=lambda: None,
        json=lambda: {"status": "ok", "sdp": "answer-sdp", "type": "answer"},
    )
    cm, instance = _mock_async_client(post_response=resp)
    try:
        data = await request_voice_offer(
            voice_agent_url="http://voice:8011",
            session_id="sess-1",
            offer_sdp="offer-sdp",
            offer_type="offer",
        )
    finally:
        cm.stop()

    assert data["sdp"] == "answer-sdp"
    call = instance.post.call_args
    assert call.args[0] == "http://voice:8011/v2/intake/offer"
    assert call.kwargs["json"]["session_id"] == "sess-1"
    assert call.kwargs["json"]["sdp"] == "offer-sdp"


async def test_request_voice_offer_raises_on_rejection():
    resp = MagicMock(
        raise_for_status=lambda: None,
        json=lambda: {"status": "rejected", "reason": "modality_conflict"},
    )
    cm, _ = _mock_async_client(post_response=resp)
    try:
        with pytest.raises(RuntimeError, match="modality_conflict"):
            await request_voice_offer(
                voice_agent_url="http://voice:8011",
                session_id="sess-1",
                offer_sdp="offer-sdp",
                offer_type="offer",
            )
    finally:
        cm.stop()


async def test_request_voice_offer_propagates_http_error():
    def _raise():
        raise httpx.HTTPStatusError("boom", request=MagicMock(), response=MagicMock())

    resp = MagicMock(raise_for_status=_raise)
    cm, _ = _mock_async_client(post_response=resp)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await request_voice_offer(
                voice_agent_url="http://voice:8011",
                session_id="sess-1",
                offer_sdp="offer-sdp",
                offer_type="offer",
            )
    finally:
        cm.stop()
