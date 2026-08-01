"""HTTP client for voice-agent control plane.

Used by switch-to-text handoff to instruct the voice agent to drain the
WebRTC session gracefully. Internal-only — authenticated with X-Internal-Secret.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import structlog

from app.config import Settings

logger = structlog.get_logger(__name__)


class VoiceAgentDrainError(RuntimeError):
    """Raised when the voice agent fails to drain a session within the timeout."""


class VoiceAgentClient:
    def __init__(self, settings: Settings):
        self._base_url = settings.VOICE_AGENT_V2_URL.rstrip("/")
        self._secret = settings.INTERNAL_API_SECRET
        self._timeout = settings.VOICE_AGENT_V2_DRAIN_TIMEOUT_S

    async def drain_session(self, session_id: UUID) -> dict[str, Any]:
        """Tell the voice agent to drain the Pipecat session for this session_id.

        Behavior:
          - 200: voice agent reports drained successfully.
          - 404: voice agent has no active session for this id — treated as a no-op
                 ("already_idle": True). Switch is idempotent.
          - 5xx or timeout: raise VoiceAgentDrainError. Caller decides whether to
            fall back to hard release of the active_modality lock.
        """
        path = f"/internal/sessions/{session_id}/drain"
        headers = {"X-Internal-Secret": self._secret, "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
                response = await client.post(path, headers=headers, json={})
        except httpx.TimeoutException as e:
            logger.error("voice_agent_drain_timeout", session_id=str(session_id), error=str(e))
            raise VoiceAgentDrainError(f"timeout after {self._timeout}s") from e
        except httpx.HTTPError as e:
            logger.error("voice_agent_drain_http_error", session_id=str(session_id), error=str(e))
            raise VoiceAgentDrainError(str(e)) from e

        if response.status_code == 404:
            logger.info("voice_agent_drain_already_idle", session_id=str(session_id))
            return {"drained": True, "already_idle": True}

        if response.status_code >= 500:
            logger.error(
                "voice_agent_drain_server_error",
                session_id=str(session_id),
                status=response.status_code,
                body=response.text[:500],
            )
            raise VoiceAgentDrainError(f"voice agent returned {response.status_code}")

        if response.status_code >= 400:
            logger.warning(
                "voice_agent_drain_client_error",
                session_id=str(session_id),
                status=response.status_code,
            )
            raise VoiceAgentDrainError(f"voice agent rejected drain: {response.status_code}")

        try:
            body = response.json()
        except ValueError:
            body = {}
        logger.info("voice_agent_drain_ok", session_id=str(session_id))
        return {"drained": True, **body}
