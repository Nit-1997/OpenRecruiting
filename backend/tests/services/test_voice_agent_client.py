"""Tests for VoiceAgentClient — the backend's HTTP shim to voice-agent."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from app.services.voice_agent_client import VoiceAgentClient, VoiceAgentDrainError


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.VOICE_AGENT_V2_URL = "http://voice-agent-v2:8011"
    s.INTERNAL_API_SECRET = "test-secret"
    s.VOICE_AGENT_V2_DRAIN_TIMEOUT_S = 10.0
    return s


@pytest.mark.asyncio
async def test_drain_session_posts_with_internal_secret(mock_settings):
    client = VoiceAgentClient(settings=mock_settings)
    sid = uuid4()
    with patch("app.services.voice_agent_client.httpx.AsyncClient") as mock_ac:
        instance = mock_ac.return_value.__aenter__.return_value
        instance.post = AsyncMock(return_value=MagicMock(
            status_code=200, json=lambda: {"drained": True}, raise_for_status=lambda: None,
        ))
        result = await client.drain_session(session_id=sid)
    assert result["drained"] is True
    call = instance.post.call_args
    assert call.args[0] == f"/internal/sessions/{sid}/drain"
    assert call.kwargs["headers"]["X-Internal-Secret"] == "test-secret"


@pytest.mark.asyncio
async def test_drain_session_returns_ok_when_no_active_session(mock_settings):
    """Voice agent returns 404 when no session is bound to that id — treat as success
    (already drained, no-op). Switch is idempotent."""
    client = VoiceAgentClient(settings=mock_settings)
    sid = uuid4()
    with patch("app.services.voice_agent_client.httpx.AsyncClient") as mock_ac:
        instance = mock_ac.return_value.__aenter__.return_value
        resp = MagicMock(status_code=404, json=lambda: {"detail": "no active session"})
        instance.post = AsyncMock(return_value=resp)
        result = await client.drain_session(session_id=sid)
    assert result == {"drained": True, "already_idle": True}


@pytest.mark.asyncio
async def test_drain_session_raises_on_5xx(mock_settings):
    client = VoiceAgentClient(settings=mock_settings)
    sid = uuid4()
    with patch("app.services.voice_agent_client.httpx.AsyncClient") as mock_ac:
        instance = mock_ac.return_value.__aenter__.return_value
        resp = MagicMock(status_code=500, text="boom")
        instance.post = AsyncMock(return_value=resp)
        with pytest.raises(VoiceAgentDrainError):
            await client.drain_session(session_id=sid)


@pytest.mark.asyncio
async def test_drain_session_raises_on_timeout(mock_settings):
    client = VoiceAgentClient(settings=mock_settings)
    sid = uuid4()
    with patch("app.services.voice_agent_client.httpx.AsyncClient") as mock_ac:
        instance = mock_ac.return_value.__aenter__.return_value
        instance.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        with pytest.raises(VoiceAgentDrainError):
            await client.drain_session(session_id=sid)


@pytest.mark.asyncio
async def test_drain_session_raises_on_4xx_client_error(mock_settings):
    """A 4xx (not 404) means the voice agent rejected the drain — raise."""
    client = VoiceAgentClient(settings=mock_settings)
    sid = uuid4()
    with patch("app.services.voice_agent_client.httpx.AsyncClient") as mock_ac:
        instance = mock_ac.return_value.__aenter__.return_value
        resp = MagicMock(status_code=400, text="bad request")
        instance.post = AsyncMock(return_value=resp)
        with pytest.raises(VoiceAgentDrainError):
            await client.drain_session(session_id=sid)


@pytest.mark.asyncio
async def test_drain_session_raises_on_generic_http_error(mock_settings):
    client = VoiceAgentClient(settings=mock_settings)
    sid = uuid4()
    with patch("app.services.voice_agent_client.httpx.AsyncClient") as mock_ac:
        instance = mock_ac.return_value.__aenter__.return_value
        instance.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(VoiceAgentDrainError):
            await client.drain_session(session_id=sid)


@pytest.mark.asyncio
async def test_drain_session_ok_when_body_not_json(mock_settings):
    """200 with an unparseable body still reports drained (body defaults to {})."""
    client = VoiceAgentClient(settings=mock_settings)
    sid = uuid4()
    with patch("app.services.voice_agent_client.httpx.AsyncClient") as mock_ac:
        instance = mock_ac.return_value.__aenter__.return_value

        def _bad_json():
            raise ValueError("not json")

        resp = MagicMock(status_code=200, json=_bad_json)
        instance.post = AsyncMock(return_value=resp)
        result = await client.drain_session(session_id=sid)
    assert result == {"drained": True}
