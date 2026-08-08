"""Tool calling for models without native function calling.

The tool schema is rendered into the prompt and the reply is validated back into
the same ToolCall shape a native call produces, so callers cannot tell the
difference. Reliability is materially lower than native tool use — see the Risks
section of the design spec before pointing a scoring path at an emulated model.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from llm_core.errors import ToolEmulationError
from llm_core.types import ToolCall

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def build_emulation_instruction(tools: list[dict[str, Any]]) -> str:
    if not tools:
        return ""
    fn = tools[0].get("function", {})
    name = fn.get("name", "tool")
    schema = json.dumps(fn.get("parameters", {}), indent=2)
    description = fn.get("description", "")
    return (
        f"You must respond by calling the tool `{name}`.\n"
        f"{description}\n\n"
        "Reply with a single JSON object and nothing else — no prose, no code fence, "
        "no explanation. The object must conform to this JSON Schema:\n"
        f"{schema}\n"
    )


def _extract_json(raw: str) -> Any:
    text = (raw or "").strip()
    if not text:
        raise ToolEmulationError("model returned an empty reply")

    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ToolEmulationError(f"model reply was not JSON: {text[:200]}")


def parse_emulated_reply(raw: str, tools: list[dict[str, Any]]) -> ToolCall:
    fn = tools[0].get("function", {})
    name = fn.get("name", "tool")
    parsed = _extract_json(raw)

    if not isinstance(parsed, dict):
        raise ToolEmulationError(f"expected a JSON object, got {type(parsed).__name__}")

    # Some models wrap the payload as {"name": ..., "arguments": {...}}.
    if set(parsed.keys()) >= {"name", "arguments"} and isinstance(parsed["arguments"], dict):
        parsed = parsed["arguments"]

    schema = fn.get("parameters", {}) or {}
    for required in schema.get("required", []) or []:
        if required not in parsed:
            raise ToolEmulationError(
                f"reply is missing required property '{required}' for tool '{name}'"
            )

    return ToolCall(id=f"emulated-{uuid.uuid4().hex[:8]}", name=name, arguments=parsed)
