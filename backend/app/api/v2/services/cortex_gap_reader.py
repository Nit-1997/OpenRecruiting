"""Read recurring candidate weakness/gaps for ONE role from Cortex.

The gap signal already lives in the Cortex graph from existing feedback
ingestion:
  (Requisition)-[:RELATES_TO {name:'HAS_ROUND'}]->(Round)
  (Candidate)-[:RELATES_TO {name:'INTERVIEWED_IN'}]->(Round)
  (Candidate)-[:RELATES_TO {name:'WEAK_IN'}]->(Competency)
Every node carries group_id = org_id; the requisition's Postgres UUID is on
`requisition_ref`. This reader counts, per competency, how many DISTINCT
candidates on this role were flagged WEAK_IN it — a recurring gap an earlier
screening round could catch.

backend holds the MCP signing key, so we mint a cortex:read service token
in-process and POST execute_query to the Cortex MCP resource server (the MCP
force-binds $org_id from the JWT). This mirrors CortexPersonaReader exactly.

This is best-effort, read-only context. Cold start, missing Cortex, a rejected
query, or any transport failure all collapse to [] — we never raise into the
caller (the suggestion service then yields should_suggest=False).

MCP query constraints honored here:
  - read-only MATCH/WITH/RETURN, no writes
  - NO subqueries (CALL{}/EXISTS{}/COUNT{}/COLLECT{}); count(DISTINCT ...) the
    aggregation FUNCTION is allowed (validator only forbids the brace forms)
  - every tenant binding has group_id = $org_id as an inline filter
  - bounded LIMIT; requisition UUID passed as $req_ref (never interpolated)
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

from app.config import get_settings
from app.services.mcp.token_minter import mint_cortex_service_token

logger = structlog.get_logger(__name__)


# Per competency on THIS role, how many distinct candidates were flagged WEAK_IN
# it. Newest/biggest gaps first so the suggestion service reads row 0 as dominant.
_GAP_CYPHER = """
MATCH (req:Requisition {group_id: $org_id})-[:RELATES_TO {name: 'HAS_ROUND'}]->(rd:Round {group_id: $org_id})
MATCH (c:Candidate {group_id: $org_id})-[:RELATES_TO {name: 'INTERVIEWED_IN'}]->(rd)
MATCH (c)-[:RELATES_TO {name: 'WEAK_IN'}]->(comp:Competency {group_id: $org_id})
WHERE req.requisition_ref = $req_ref
RETURN comp.name AS competency, count(DISTINCT c) AS weak_candidates
ORDER BY weak_candidates DESC, competency ASC
LIMIT 10
"""


def _parse_rows(resp: dict) -> list[dict]:
    """Cortex wraps rows in {status, data}; treat rejected/error/empty as []."""
    try:
        parsed = json.loads(resp["result"]["content"][0]["text"])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return []
    if isinstance(parsed, dict):
        if parsed.get("status") not in (None, "ok"):
            logger.warning("cortex_gap_query_rejected", error=parsed.get("error"))
            return []
        rows = parsed.get("data") or []
    elif isinstance(parsed, list):
        rows = parsed
    else:
        return []
    return [r for r in rows if isinstance(r, dict)]


class CortexGapReader:
    """Reads recurring candidate-weakness counts per competency for one role.

    The single MCP HTTP call lives behind `_execute_query` so tests can mock it
    without a network or a real token.
    """

    async def read_recurring_gaps(
        self, *, org_id: str, org_name: str, requisition_id: str
    ) -> list[dict]:
        """Return [{competency, weak_candidates}, ...] for the role, biggest gap
        first. Never raises: cold start / no Cortex / rejected query / transport
        error all return []."""
        try:
            token, _ttl = mint_cortex_service_token(org_id=org_id, org_name=org_name)
        except Exception as exc:  # noqa: BLE001 — no Cortex config -> no suggestion
            logger.warning("cortex_gap_token_failed", error=str(exc))
            return []

        try:
            resp = await self._execute_query(
                token, _GAP_CYPHER, {"req_ref": requisition_id}
            )
        except Exception as exc:  # noqa: BLE001 — best-effort read
            logger.warning("cortex_gap_query_failed", error=str(exc))
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
    """Extract the JSON-RPC payload from a Streamable-HTTP SSE response body."""
    payload: dict[str, Any] | None = None
    for line in body.splitlines():
        if line.startswith("data: "):
            payload = json.loads(line[len("data: "):])
    if payload is None:
        raise ValueError("MCP SSE response had no data lines")
    return payload
