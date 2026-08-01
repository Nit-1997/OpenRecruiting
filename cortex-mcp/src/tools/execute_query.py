"""execute_query — validate, force-bind $org_id, execute, return structured result.

Result envelope:
  { "status": "ok",       "data": [...], "error": null }
  { "status": "rejected", "data": null,  "error": "<reason>" }
  { "status": "error",    "data": null,  "error": "<reason>" }

The caller's LLM is expected to read `error` on non-ok status and fix its
query. We never half-fail — either the query passes validation + executes,
or we surface a single, structured reason.
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog
from neo4j.exceptions import Neo4jError

from src.auth.context import AuthContext
from src.clients.neo4j_client import run_read_query
from src.config.settings import get_settings
from src.validator import ValidationError, validate_cypher
from src.validator.result_guard import CrossTenantLeak, check_result

logger = structlog.get_logger(__name__)


async def execute_query(
    query: str,
    auth: AuthContext,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = get_settings()

    # 1. Validate (deterministic, no side effects).
    try:
        validate_cypher(query)
    except ValidationError as e:
        logger.info("query_rejected", org_id=auth.org_id, reason=str(e))
        return {"status": "rejected", "data": None, "error": str(e)}

    # 2. Force-bind $org_id from the JWT. We never trust caller-provided values
    # for this parameter — overwriting is the whole point.
    bound = dict(params or {})
    if "org_id" in bound and bound["org_id"] != auth.org_id:
        logger.warning(
            "caller_supplied_org_id_overwritten",
            org_id=auth.org_id,
            attempted=bound["org_id"],
        )
    bound["org_id"] = auth.org_id

    # 3. Execute against Neo4j.
    try:
        rows = await asyncio.wait_for(
            run_read_query(
                query=query,
                params=bound,
                timeout_seconds=settings.query_timeout_seconds,
                max_rows=settings.query_max_rows,
            ),
            timeout=settings.query_timeout_seconds + 2,
        )

        # 4. Defense-in-depth: scan returned rows for cross-tenant leaks.
        # The validator should have prevented this at parse time, but if a
        # future Cypher construct slips past the tokenizer, we catch it
        # here against the actual data. Fails closed — the LLM sees a
        # clear "cross-org reads are forbidden" message and retries.
        try:
            check_result(rows, auth.org_id)
        except CrossTenantLeak as leak:
            logger.error(
                "cross_tenant_leak_blocked",
                org_id=auth.org_id,
                query=query[:200],
                reason=str(leak),
            )
            return {"status": "rejected", "data": None, "error": str(leak)}

        truncated = len(rows) >= settings.query_max_rows
        return {
            "status": "ok",
            "data": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "error": None,
        }
    except asyncio.TimeoutError:
        logger.warning("query_timeout", org_id=auth.org_id)
        return {
            "status": "error",
            "data": None,
            "error": (
                f"Query exceeded {settings.query_timeout_seconds}s timeout. "
                f"Add filters or use LIMIT to reduce work."
            ),
        }
    except Neo4jError as e:
        logger.warning("neo4j_error", org_id=auth.org_id, error=str(e))
        return {
            "status": "error",
            "data": None,
            "error": f"Neo4j error: {e.message if hasattr(e, 'message') else str(e)}",
        }
    except Exception as e:  # pragma: no cover — last-resort guard
        logger.exception("execute_query_failed", org_id=auth.org_id)
        return {
            "status": "error",
            "data": None,
            "error": f"Internal error: {type(e).__name__}",
        }
