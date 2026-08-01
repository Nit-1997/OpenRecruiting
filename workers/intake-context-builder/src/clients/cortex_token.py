"""Fetch a per-org Cortex MCP token from the v2 backend.

The backend (localhost:8004) holds the MCP signing key; this Lambda never does.
We authenticate with X-Internal-Secret and receive a short-lived JWT scoped to
the session's organization, which we then present to Cortex MCP.

Per the Lambda mandatory rules: this opens and closes its own httpx client
inside the call (no module-scoped async client bound to the event loop).
"""

from __future__ import annotations

import httpx
import structlog

logger = structlog.get_logger(__name__)


async def fetch_service_token(token_url: str, internal_secret: str, organization_id: str) -> str:
    """Return a Cortex MCP bearer token bound to organization_id. Raises on failure."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
        resp = await client.post(
            token_url,
            headers={"X-Internal-Secret": internal_secret},
            json={"organization_id": organization_id},
        )
    resp.raise_for_status()
    token = resp.json().get("token")
    if not token:
        raise ValueError("cortex service-token response had no token")
    return token
