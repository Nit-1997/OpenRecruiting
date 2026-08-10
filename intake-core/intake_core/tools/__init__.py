"""Tools bound to the intake agent LLM."""

from __future__ import annotations

from typing import Any

import structlog

from intake_core.tools.schemas import ALL_TOOLS, ALL_TOOLS_OPENAI
from intake_core.tools.update_answer import handle_update_answer, ahandle_update_answer
from intake_core.tools.mark_status import handle_mark_status, ahandle_mark_status

logger = structlog.get_logger(__name__)

INTAKE_TOOLS_ANTHROPIC: list[dict] = ALL_TOOLS
# The same two tools in the shape the LiteLLM gateway speaks. The backend text
# runner uses this one; the voice agent still uses the Anthropic list above.
INTAKE_TOOLS_OPENAI: list[dict] = ALL_TOOLS_OPENAI


def handle_tool_call(
    supabase_client,
    session_id: str,
    tool_call: dict[str, Any],
    turn_idx: int = 0,
) -> dict[str, Any]:
    """Dispatch a tool call dict to the correct handler (sync — Lambda path).

    tool_call shape: {"id": "...", "name": "update_answer"|"mark_status", "input": {...}}
    Returns the handler's result dict: {ok, ...}.
    """
    name = tool_call.get("name")
    args = tool_call.get("input") or {}

    if name == "update_answer":
        return handle_update_answer(
            client=supabase_client,
            session_id=session_id,
            args=args,
            turn_idx=turn_idx,
        )
    if name == "mark_status":
        return handle_mark_status(
            client=supabase_client,
            session_id=session_id,
            args=args,
        )

    logger.warning("unknown_tool_call", session_id=session_id, name=name)
    return {"ok": False, "error": f"unknown tool: {name}"}


async def ahandle_tool_call(
    supabase_client,
    session_id: str,
    tool_call: dict[str, Any],
    turn_idx: int = 0,
) -> dict[str, Any]:
    """Async variant — for the FastAPI text path (SupabaseAdminClient)."""
    name = tool_call.get("name")
    args = tool_call.get("input") or {}

    if name == "update_answer":
        return await ahandle_update_answer(
            client=supabase_client,
            session_id=session_id,
            args=args,
            turn_idx=turn_idx,
        )
    if name == "mark_status":
        return await ahandle_mark_status(
            client=supabase_client,
            session_id=session_id,
            args=args,
        )

    logger.warning("unknown_tool_call", session_id=session_id, name=name)
    return {"ok": False, "error": f"unknown tool: {name}"}


__all__ = [
    "INTAKE_TOOLS_ANTHROPIC",
    "INTAKE_TOOLS_OPENAI",
    "handle_tool_call",
    "ahandle_tool_call",
]
