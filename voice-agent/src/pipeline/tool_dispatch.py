"""Map Anthropic tool calls to intake_core handlers.

Voice agent integration point: when Pipecat's LLM emits a tool call, the
LLM service hands it off here. We route to the appropriate intake-core handler.
"""

from __future__ import annotations

from typing import Any

import structlog

from intake_core.tools.update_answer import handle_update_answer
from intake_core.tools.mark_status import handle_mark_status

logger = structlog.get_logger(__name__)


def dispatch_tool_call(
    client,
    session_id: str,
    tool_name: str,
    tool_args: dict[str, Any],
    turn_idx: int,
) -> dict[str, Any]:
    """Synchronous dispatch. Returns the handler's result dict."""
    if tool_name == "update_answer":
        return handle_update_answer(
            client=client, session_id=session_id, args=tool_args, turn_idx=turn_idx,
        )
    if tool_name == "mark_status":
        return handle_mark_status(client=client, session_id=session_id, args=tool_args)
    logger.warning("dispatch_unknown_tool", tool_name=tool_name)
    return {"ok": False, "error": f"unknown tool: {tool_name}"}
