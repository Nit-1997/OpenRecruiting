"""Thin wrapper around AsyncAnthropic.messages.stream() that exposes a tagged
event iterator: ('text', str) | ('tool_call', dict) | ('done', dict).

Decouples text_runner from Anthropic SDK internals — tests can mock this.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import structlog

logger = structlog.get_logger(__name__)


async def stream_llm_turn(
    client,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    max_tokens: int = 2048,
) -> AsyncIterator[tuple[str, Any]]:
    """Stream a single assistant turn. Yields tagged events.

    ('text', str)      — incremental prose chunk
    ('tool_call', {...}) — completed tool call with id/name/input dict
    ('done', {...})    — final message metadata: {text, stop_reason}

    Note: tool calls are emitted only after their input JSON is fully assembled
    (on content_block_stop). text chunks stream as they arrive.
    """
    stream_kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    if tools:
        stream_kwargs["tools"] = tools

    async with client.messages.stream(**stream_kwargs) as stream:
        active_tool: dict[str, Any] | None = None
        tool_input_buf: str = ""

        async for event in stream:
            ev_type = getattr(event, "type", None)

            if ev_type == "content_block_start":
                block = getattr(event, "content_block", None)
                btype = getattr(block, "type", None)
                if btype == "tool_use":
                    active_tool = {
                        "id": getattr(block, "id", None),
                        "name": getattr(block, "name", None),
                        "input": {},
                    }
                    tool_input_buf = ""

            elif ev_type == "content_block_delta":
                delta = getattr(event, "delta", None)
                dtype = getattr(delta, "type", None)
                if dtype == "text_delta":
                    text = getattr(delta, "text", "") or ""
                    if text:
                        yield ("text", text)
                elif dtype == "input_json_delta":
                    tool_input_buf += getattr(delta, "partial_json", "") or ""

            elif ev_type == "content_block_stop":
                if active_tool is not None:
                    try:
                        active_tool["input"] = json.loads(tool_input_buf) if tool_input_buf else {}
                    except json.JSONDecodeError:
                        logger.warning(
                            "tool_input_json_invalid",
                            buf=tool_input_buf[:300],
                            name=active_tool.get("name"),
                        )
                        active_tool["input"] = {}
                    yield ("tool_call", active_tool)
                    active_tool = None
                    tool_input_buf = ""

        final = await stream.get_final_message()
        text_blocks = [
            getattr(b, "text", "") for b in (final.content or [])
            if getattr(b, "type", None) == "text"
        ]
        yield ("done", {
            "text": "".join(text_blocks),
            "stop_reason": getattr(final, "stop_reason", None),
        })
