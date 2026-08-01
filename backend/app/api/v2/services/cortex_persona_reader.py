"""Read the org's REAL interviewer style from Cortex (the screening-persona "map").

The interviewer traits already exist in the Cortex graph as edges written by
existing ingestion:
  (Interviewer)-[:RELATES_TO {name:'DEMONSTRATES'}]->(Trait)
  (Interviewer)-[:RELATES_TO {name:'CONDUCTED'}]->(Round)
  (Requisition)-[:RELATES_TO {name:'HAS_ROUND'}]->(Round)
Every node carries group_id = org_id; the edge type is the single RELATES_TO with
the semantic name in the `name` property.

backend holds the MCP signing key, so we mint a cortex:read service token
in-process (no HTTP round-trip to /internal/cortex-token) and POST execute_query
to the Cortex MCP resource server. The MCP force-binds $org_id from the JWT.

This is best-effort, read-only context. Cold start, missing Cortex, a rejected
query, or any transport failure all collapse to [] — we never raise into the
caller (the reduce service falls back to a generic persona).

MCP query constraints honored here:
  - read-only MATCH/RETURN, no writes
  - NO subqueries (CALL{}/EXISTS{}/COUNT{}/COLLECT{})
  - every tenant binding has group_id = $org_id as a top-level AND
  - bounded paths, bounded LIMIT
  - user-supplied role title passed as $title (never interpolated)
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

from app.config import get_settings
from app.services.mcp.token_minter import mint_cortex_service_token

logger = structlog.get_logger(__name__)


# Interviewers who CONDUCTED a round for a requisition matching the role title,
# and the style traits they DEMONSTRATE. Filtered to this role; if it returns
# nothing the caller falls back to the org-wide query below.
_SIGNAL_CYPHER = """
MATCH (req:Requisition)-[:RELATES_TO {name: 'HAS_ROUND'}]->(r:Round)
MATCH (iv:Interviewer)-[:RELATES_TO {name: 'CONDUCTED'}]->(r)
MATCH (iv)-[d:RELATES_TO {name: 'DEMONSTRATES'}]->(t:Trait)
WHERE req.group_id = $org_id AND r.group_id = $org_id
  AND iv.group_id = $org_id AND t.group_id = $org_id
  AND toLower(req.role_title) CONTAINS toLower($title)
RETURN t.name AS trait, t.category AS category, d.fact AS evidence,
       d.pattern_frequency AS frequency
LIMIT 100
"""

# Broader fallback: any interviewer's DEMONSTRATES traits across the org, used
# when the role-scoped query yields nothing (e.g. a brand-new role title).
_SIGNAL_CYPHER_ORG = """
MATCH (iv:Interviewer)-[d:RELATES_TO {name: 'DEMONSTRATES'}]->(t:Trait)
WHERE iv.group_id = $org_id AND t.group_id = $org_id
RETURN t.name AS trait, t.category AS category, d.fact AS evidence,
       d.pattern_frequency AS frequency
LIMIT 100
"""


def _parse_rows(resp: dict) -> list[dict]:
    """Cortex wraps rows in {status, data}; treat rejected/error/empty as []."""
    try:
        parsed = json.loads(resp["result"]["content"][0]["text"])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return []
    if isinstance(parsed, dict):
        if parsed.get("status") not in (None, "ok"):
            logger.warning("cortex_persona_query_rejected", error=parsed.get("error"))
            return []
        rows = parsed.get("data") or []
    elif isinstance(parsed, list):
        rows = parsed
    else:
        return []
    return [r for r in rows if isinstance(r, dict)]


class CortexPersonaReader:
    """Reads interviewer style traits from Cortex for one role.

    The single MCP HTTP call lives behind `_execute_query` so tests can mock it
    without a network or a real token.
    """

    async def read_interviewer_signal(
        self, *, org_id: str, org_name: str, role_title: str
    ) -> list[dict]:
        """Return [{trait, category, evidence, frequency}, ...] for the role.

        Never raises: cold start / no Cortex / rejected query / transport error
        all return []. Falls back to an org-wide trait query if the role-scoped
        query is empty.
        """
        try:
            token, _ttl = mint_cortex_service_token(org_id=org_id, org_name=org_name)
        except Exception as exc:  # noqa: BLE001 — no Cortex config -> generic persona
            logger.warning("cortex_persona_token_failed", error=str(exc))
            return []

        rows = await self._query(token, _SIGNAL_CYPHER, {"title": role_title})
        if not rows:
            rows = await self._query(token, _SIGNAL_CYPHER_ORG, {})
        return rows

    async def _query(self, token: str, cypher: str, params: dict) -> list[dict]:
        try:
            resp = await self._execute_query(token, cypher, params)
        except Exception as exc:  # noqa: BLE001 — best-effort read
            logger.warning("cortex_persona_query_failed", error=str(exc))
            return []
        return _parse_rows(resp)

    async def _execute_query(
        self, token: str, query: str, params: dict
    ) -> dict[str, Any]:
        """The single mockable MCP HTTP seam. POSTs a JSON-RPC tools/call for
        execute_query and unwraps the Streamable-HTTP SSE / JSON response."""
        base_url = get_settings().CORTEX_MCP_URL
        async with httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
            },
            timeout=httpx.Timeout(15.0, connect=5.0),
        ) as client:
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "execute_query",
                        "arguments": {"query": query, "params": params},
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
    """Extract the JSON-RPC payload from a Streamable-HTTP SSE response body.

    For a non-streaming tools/call the transport sends one `event: message`
    with a single `data: {...}` line carrying the JSON-RPC body.
    """
    payload: dict[str, Any] | None = None
    for line in body.splitlines():
        if line.startswith("data: "):
            payload = json.loads(line[len("data: "):])
    if payload is None:
        raise ValueError("MCP SSE response had no data lines")
    return payload
