"""Fire-and-forget audit writer for MCP tool invocations.

Every tool call posts one row to `public.mcp_audit_log` in Supabase. We
deliberately:

  * Use the Supabase REST endpoint directly (no `supabase-py` dep).
  * Use the service-role key — the audit table denies all non-service
    access via RLS, so customer tokens can't read or write it.
  * Truncate the query + error fields before sending so we never blow
    Supabase's row size limit even on degenerate inputs.
  * Make the write fire-and-forget via `asyncio.create_task` so a slow
    or failing Supabase doesn't block the MCP response path. The trade-off:
    if Supabase is down for an hour, we lose audit rows for that hour —
    but we never delay a customer query.

The module-level client lifecycle is owned by `lifespan` in `src/main.py`
(start at boot, close at shutdown). The MCP server runs as a regular
uvicorn process — no warm-Lambda event-loop pitfall to manage.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from src.auth.context import AuthContext
from src.config.settings import get_settings

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class AuditEvent:
    user_id: str
    org_id: str | None
    client_id: str | None
    tool_name: str
    query: str | None
    query_param_keys: list[str] | None
    status: str                     # ok | rejected | error | rate_limited
    row_count: int | None
    truncated: bool | None
    error_message: str | None
    latency_ms: int
    user_agent: str | None
    ip_address: str | None
    request_id: str | None


_async_client: httpx.AsyncClient | None = None


async def init_audit_client() -> None:
    """Construct the HTTP client at app startup. Idempotent."""
    global _async_client
    if _async_client is not None:
        return
    settings = get_settings()
    if not settings.audit_enabled or not settings.supabase_url:
        logger.info("audit_disabled",
                    enabled=settings.audit_enabled,
                    have_url=bool(settings.supabase_url))
        return
    _async_client = httpx.AsyncClient(
        base_url=settings.supabase_url.rstrip("/"),
        timeout=settings.audit_timeout_seconds,
        headers={
            "apikey": settings.supabase_secret_key,
            "Authorization": f"Bearer {settings.supabase_secret_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
    )
    logger.info("audit_client_ready", url=settings.supabase_url)


async def close_audit_client() -> None:
    """Tear down at app shutdown."""
    global _async_client
    if _async_client is None:
        return
    try:
        await _async_client.aclose()
    except Exception as e:  # pragma: no cover — last-resort guard
        logger.warning("audit_client_close_failed", error=str(e))
    _async_client = None


def emit(event: AuditEvent) -> None:
    """Schedule a non-blocking write of one audit row.

    Returns immediately. Failures inside the background task are logged
    but never propagated — auditing is best-effort.
    """
    settings = get_settings()
    if not settings.audit_enabled:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Called from a sync context — synthesize a one-shot loop for the
        # write. (Shouldn't happen in normal MCP flow; defensive.)
        logger.warning("audit_emit_no_loop", tool=event.tool_name)
        return

    loop.create_task(_send(event))


async def _send(event: AuditEvent) -> None:
    settings = get_settings()
    if _async_client is None:
        # Audit disabled / not initialised — log locally and move on so the
        # event isn't completely invisible.
        logger.info(
            "audit_local_only",
            user_id=event.user_id,
            org_id=event.org_id,
            tool=event.tool_name,
            status=event.status,
            row_count=event.row_count,
            latency_ms=event.latency_ms,
        )
        return

    payload = _serialize(event, settings.audit_query_max_chars, settings.audit_error_max_chars)
    try:
        resp = await _async_client.post(
            "/rest/v1/mcp_audit_log",
            content=json.dumps(payload),
        )
        if resp.status_code >= 400:
            # Log the failure but never raise — fire-and-forget.
            logger.warning(
                "audit_write_failed",
                status=resp.status_code,
                body=resp.text[:300],
                tool=event.tool_name,
            )
    except Exception as e:
        logger.warning("audit_write_exception", error=str(e), tool=event.tool_name)


def _serialize(event: AuditEvent, max_q: int, max_err: int) -> dict[str, Any]:
    return {
        "user_id": event.user_id,
        "org_id": event.org_id,
        "client_id": event.client_id,
        "tool_name": event.tool_name,
        "query": _truncate(event.query, max_q),
        "query_param_keys": event.query_param_keys,
        "status": event.status,
        "row_count": event.row_count,
        "truncated": event.truncated,
        "error_message": _truncate(event.error_message, max_err),
        "latency_ms": event.latency_ms,
        "user_agent": event.user_agent,
        "ip_address": event.ip_address,
        "request_id": event.request_id,
    }


def _truncate(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def build_event(
    *,
    auth: AuthContext,
    tool_name: str,
    status: str,
    start_monotonic: float,
    query: str | None = None,
    params: dict[str, Any] | None = None,
    row_count: int | None = None,
    truncated: bool | None = None,
    error_message: str | None = None,
    user_agent: str | None = None,
    ip_address: str | None = None,
    request_id: str | None = None,
    client_id: str | None = None,
) -> AuditEvent:
    """Shape an event from the per-request context.

    We deliberately log the PARAM KEYS, not param values — values can be
    PII (candidate names, requisition titles) and would defeat the purpose
    of a tightly-scoped audit table.
    """
    return AuditEvent(
        user_id=auth.user_id,
        org_id=auth.org_id,
        client_id=client_id,
        tool_name=tool_name,
        query=query,
        query_param_keys=sorted(params.keys()) if params else None,
        status=status,
        row_count=row_count,
        truncated=truncated,
        error_message=error_message,
        latency_ms=int((time.monotonic() - start_monotonic) * 1000),
        user_agent=user_agent,
        ip_address=ip_address,
        request_id=request_id,
    )
