"""HTTP client for Cortex MCP. Reuses module-scoped httpx.AsyncClient per
Lambda mandatory rules — must be closed in pipeline.run_pipeline's finally.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

_async_client: Optional[httpx.AsyncClient] = None


def get_mcp_client(mcp_url: str, jwt: str) -> httpx.AsyncClient:
    global _async_client
    if _async_client is None:
        _async_client = httpx.AsyncClient(
            base_url=mcp_url,
            headers={
                "Authorization": f"Bearer {jwt}",
                "Accept": "application/json, text/event-stream",
            },
            timeout=httpx.Timeout(15.0, connect=5.0),
        )
    return _async_client


async def close_mcp_client() -> None:
    global _async_client
    if _async_client is not None:
        try:
            await _async_client.aclose()
        except Exception as e:
            logger.warning("cortex_mcp_close_failed", error=str(e))
        _async_client = None


async def execute_cypher(client: httpx.AsyncClient, cypher: str, params: dict[str, Any]) -> dict[str, Any]:
    """Call MCP's execute_query tool. $org_id is force-bound server-side from JWT."""
    response = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "execute_query",
                "arguments": {"query": cypher, "params": params},
            },
            "id": 1,
        },
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        return _parse_sse_jsonrpc(response.text)
    return response.json()


def _parse_sse_jsonrpc(body: str) -> dict[str, Any]:
    """Extract the JSON-RPC payload from a Streamable-HTTP SSE response.

    The MCP Streamable-HTTP transport responds to one POST with one or more
    `data:` lines per SSE event. For a non-streaming tools/call there is a
    single `event: message` with one `data: {...}` carrying the JSON-RPC body.
    """
    payload: dict[str, Any] | None = None
    for line in body.splitlines():
        if line.startswith("data: "):
            payload = json.loads(line[len("data: "):])
    if payload is None:
        raise ValueError("MCP SSE response had no data lines")
    return payload
