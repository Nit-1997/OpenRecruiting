"""Stage 3: parallel Cortex queries. Mode-dependent."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import structlog

from ..clients.cortex_mcp import execute_cypher
from .check_context import Mode

logger = structlog.get_logger(__name__)


SIMILAR_REQS_CYPHER = """
MATCH (req:Requisition {group_id: $org_id})
WHERE toLower(req.role_title) CONTAINS toLower($title)
RETURN req.role_title AS role_title,
       req.experience_min_years AS experience_min_years,
       req.experience_max_years AS experience_max_years,
       req.role_location AS location
LIMIT 5
"""

SKILLS_REQUIRED_CYPHER = """
MATCH (req:Requisition {group_id: $org_id})-[:RELATES_TO {name: 'REQUIRES'}]->(s:Skill {group_id: $org_id})
WHERE toLower(req.role_title) CONTAINS toLower($title)
RETURN s.name AS name, count(*) AS count
ORDER BY count DESC
LIMIT 15
"""

SKILLS_NICE_CYPHER = """
MATCH (req:Requisition {group_id: $org_id})-[:RELATES_TO {name: 'NICE_TO_HAVE'}]->(s:Skill {group_id: $org_id})
WHERE toLower(req.role_title) CONTAINS toLower($title)
RETURN s.name AS name, count(*) AS count
ORDER BY count DESC
LIMIT 10
"""

TRAITS_CYPHER_FULL = """
MATCH (req:Requisition {group_id: $org_id})-[:RELATES_TO {name: 'VALUES'}]->(t:Trait {group_id: $org_id})
WHERE toLower(req.role_title) CONTAINS toLower($title)
RETURN t.name AS name, t.polarity AS polarity, count(*) AS count
ORDER BY count DESC
LIMIT 10
"""

TRAITS_CYPHER_ORG = """
MATCH (req:Requisition {group_id: $org_id})-[:RELATES_TO {name: 'VALUES'}]->(t:Trait {group_id: $org_id})
RETURN t.name AS name, t.polarity AS polarity, count(*) AS count
ORDER BY count DESC
LIMIT 10
"""

ROUNDS_CYPHER = """
MATCH (req:Requisition {group_id: $org_id})-[:RELATES_TO {name: 'HAS_ROUND'}]->(r:Round {group_id: $org_id})
WHERE toLower(req.role_title) CONTAINS toLower($title)
RETURN r.name AS name, count(*) AS count
ORDER BY count DESC
LIMIT 10
"""


def _parse_rows(resp: dict) -> list[dict]:
    """Cortex wraps rows in {status, data, ...}; older builds returned a bare
    row list. Accept both, and treat a rejected/errored query as no rows."""
    try:
        parsed = json.loads(resp["result"]["content"][0]["text"])
        if isinstance(parsed, dict):
            if parsed.get("status") not in (None, "ok"):
                logger.warning("cortex_query_rejected", error=parsed.get("error"))
                return []
            return parsed.get("data") or []
        return parsed
    except (KeyError, IndexError, json.JSONDecodeError):
        return []


async def query_cortex(
    mcp_client: httpx.AsyncClient,
    mode: Mode,
    role_title: str,
) -> dict[str, Any]:
    empty = {"similar_reqs": [], "skills_required": [], "skills_nice": [], "traits": [], "rounds": []}
    if mode == Mode.COLD:
        return empty

    if mode == Mode.ORG_ONLY:
        # Only the trait query (org-wide)
        resp = await execute_cypher(mcp_client, TRAITS_CYPHER_ORG, {})
        return {**empty, "traits": _parse_rows(resp)}

    # FULL_CONTEXT: parallel queries
    coros = [
        execute_cypher(mcp_client, SIMILAR_REQS_CYPHER, {"title": role_title}),
        execute_cypher(mcp_client, SKILLS_REQUIRED_CYPHER, {"title": role_title}),
        execute_cypher(mcp_client, SKILLS_NICE_CYPHER, {"title": role_title}),
        execute_cypher(mcp_client, TRAITS_CYPHER_FULL, {"title": role_title}),
        execute_cypher(mcp_client, ROUNDS_CYPHER, {"title": role_title}),
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)

    parsed = {}
    keys = ["similar_reqs", "skills_required", "skills_nice", "traits", "rounds"]
    for key, result in zip(keys, results):
        if isinstance(result, Exception):
            logger.warning("cortex_query_failed", key=key, error=str(result))
            parsed[key] = []
        else:
            parsed[key] = _parse_rows(result)
    return parsed
