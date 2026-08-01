"""Stage 1: determine operating mode based on what Cortex contains for this org."""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

import httpx
import structlog

from ..clients.cortex_mcp import execute_cypher

logger = structlog.get_logger(__name__)


class Mode(str, Enum):
    COLD = "COLD"
    ORG_ONLY = "ORG_ONLY"
    FULL_CONTEXT = "FULL_CONTEXT"


# Cortex's validator rejects label-less bindings like `(n)` — every node
# binding must carry an explicit label. Downstream context (both ORG_ONLY and
# FULL_CONTEXT modes) is Requisition-anchored, so "does this org have any
# usable context" is correctly probed as "does it have any Requisition".
HAS_ANY_CYPHER = """
MATCH (req:Requisition {group_id: $org_id}) RETURN count(req) > 0 AS has_any LIMIT 1
"""

SIMILAR_COUNT_CYPHER = """
MATCH (req:Requisition {group_id: $org_id})
WHERE toLower(req.role_title) CONTAINS toLower($title)
RETURN count(req) AS similar_count
"""


async def check_context(mcp_client: httpx.AsyncClient, role_title: str) -> dict[str, Any]:
    """Returns {mode, has_any, similar_count}."""
    # NOTE: $org_id is force-bound server-side by MCP from JWT — don't pass it
    resp1 = await execute_cypher(mcp_client, HAS_ANY_CYPHER, {})
    has_any = _extract_first_row_field(resp1, "has_any", default=False)

    if not has_any:
        return {"mode": Mode.COLD, "has_any": False, "similar_count": 0}

    resp2 = await execute_cypher(mcp_client, SIMILAR_COUNT_CYPHER, {"title": role_title})
    similar_count = int(_extract_first_row_field(resp2, "similar_count", default=0))

    mode = Mode.FULL_CONTEXT if similar_count > 0 else Mode.ORG_ONLY
    return {"mode": mode, "has_any": True, "similar_count": similar_count}


def _extract_first_row_field(resp: dict, field: str, default: Any) -> Any:
    """MCP returns a JSON-string in content[0].text. Cortex wraps rows in an
    envelope {status, data, row_count, error}; older builds returned a bare row
    list. Handle both, and surface query rejections instead of silently
    defaulting."""
    try:
        content = resp["result"]["content"][0]["text"]
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            if parsed.get("status") not in (None, "ok"):
                logger.warning(
                    "cortex_query_rejected", field=field, error=parsed.get("error")
                )
                return default
            rows = parsed.get("data")
        else:
            rows = parsed
        if not rows:
            return default
        return rows[0].get(field, default)
    except (KeyError, IndexError, json.JSONDecodeError):
        logger.warning("mcp_response_unparseable", resp=resp, field=field)
        return default
