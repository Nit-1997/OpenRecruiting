"""HTTP client to the voice-agent service."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


async def request_voice_offer(
    *,
    voice_agent_url: str,
    session_id: str,
    offer_sdp: str,
    offer_type: str,
    timeout_secs: float = 15.0,
) -> dict[str, Any]:
    """POST /v2/intake/offer to the voice agent, return its answer payload.

    Raises RuntimeError if the voice agent rejects (e.g. modality conflict).
    """
    async with httpx.AsyncClient(timeout=timeout_secs) as client:
        resp = await client.post(
            f"{voice_agent_url}/v2/intake/offer",
            json={
                "session_id": session_id,
                "sdp": offer_sdp,
                "type": offer_type,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "rejected":
            reason = data.get("reason", "unknown")
            logger.warning("voice_v2_offer_rejected", session_id=session_id, reason=reason)
            raise RuntimeError(f"voice agent rejected offer: {reason}")
        return data
