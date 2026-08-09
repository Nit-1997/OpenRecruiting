"""Tool calling for models without native function calling.

The tool schema is rendered into the prompt and the reply is coerced back into the
same ToolCall shape a native call produces, so callers cannot tell the difference.
Reliability is materially lower than native tool use — see the Risks section of the
design spec before pointing a scoring path at an emulated model.

Validation is PRESENCE-ONLY. Required properties are checked for presence and
nothing else: types, enums, formats, and nested-object constraints are NOT checked,
so both {"title": null} and {"title": 42} satisfy a {"title": {"type": "string"}}
schema. Do not treat a returned ToolCall as schema-valid — if you need that
guarantee, validate in the caller. Enforcing the schema properly would require a
jsonschema dependency, which this package's dependency constraint forbids.

Tools must arrive in OpenAI shape:
    {"type": "function", "function": {"name", "description", "parameters"}}
Anthropic-shaped specs ({"name", "input_schema"}) are rejected rather than silently
misread — a missing "function" key would otherwise yield a tool named "tool" with an
empty schema, disabling the presence check and returning arguments under a name no
dispatcher knows.

`validate_tool_shape` is the one place that check lives, and it is deliberately not
private to this module: `LLMClient` calls it on the native path too, so a
malformed spec fails identically whether the alias emulates tools or not.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from llm_core.errors import ToolEmulationError
from llm_core.types import ToolCall

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

_MAX_SNIPPET = 200
_MAX_KEYS = 10


def _snippet(value: Any, limit: int = _MAX_SNIPPET) -> str:
    """A bounded, single-line rendering of offending output, safe for a log line."""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit] + "..."


def _keys(payload: dict[str, Any]) -> list[str]:
    return sorted(payload.keys())[:_MAX_KEYS]


def validate_tool_shape(tools: list[dict[str, Any]]) -> list[tuple[str, str, dict[str, Any]]]:
    """Validate OpenAI tool shape up front, returning (name, description, schema).

    Every rejection here is a caller bug that would otherwise degrade silently.

    This runs on BOTH dispatch paths, not just the emulated one. `LLMClient`
    calls it before it asks whether the alias supports tools, so an
    Anthropic-shaped spec is rejected here with the same message whether it was
    headed for native `tools` or for a prompt-rendered schema. It used to be
    reachable only through emulation, which meant a tool-capable alias forwarded
    the malformed spec to the gateway and failed as an opaque provider 400 at
    runtime. Nearly fifty tool specs in this repo still carry `input_schema`, so
    that is the expected mistake during migration, not an exotic one.
    """
    if not tools:
        raise ToolEmulationError(
            "no tools supplied; at least one tool in OpenAI shape "
            "{'type': 'function', 'function': {...}} is required"
        )

    entries: list[tuple[str, str, dict[str, Any]]] = []
    for index, tool in enumerate(tools):
        if not isinstance(tool, dict):
            raise ToolEmulationError(
                f"tool at index {index} is not a dict, got {type(tool).__name__}"
            )

        if "function" not in tool:
            named = tool.get("name")
            label = f"'{named}'" if isinstance(named, str) and named else f"at index {index}"
            raise ToolEmulationError(
                f"tool {label} is not in OpenAI shape: expected a 'function' key holding "
                f"{{'name', 'description', 'parameters'}}, got keys {_keys(tool)}. "
                "Anthropic-shaped specs using 'input_schema' must be converted to "
                "{'type': 'function', 'function': {'name', 'description', 'parameters'}} "
                "before they reach llm_core, which does not translate them."
            )

        fn = tool.get("function") or {}
        if not isinstance(fn, dict):
            raise ToolEmulationError(
                f"tool at index {index} has a non-dict 'function', got {type(fn).__name__}"
            )

        name = fn.get("name")
        if not isinstance(name, str) or not name:
            raise ToolEmulationError(
                f"tool at index {index} has no usable 'function.name', got keys {_keys(fn)}"
            )

        entries.append((name, fn.get("description") or "", fn.get("parameters") or {}))

    return entries


def build_emulation_instruction(tools: list[dict[str, Any]]) -> str:
    entries = validate_tool_shape(tools)

    if len(entries) == 1:
        name, description, schema = entries[0]
        return (
            f"You must respond by calling the tool `{name}`.\n"
            f"{description}\n\n"
            "Reply with a single JSON object and nothing else — no prose, no code fence, "
            "no explanation. The object must conform to this JSON Schema:\n"
            f"{json.dumps(schema, indent=2)}\n"
        )

    # With more than one tool the choice must be explicit, so the reply carries the
    # tool name in an envelope rather than leaving us to guess which schema applies.
    blocks = [
        f"Tool `{name}`: {description}\n"
        f"Its arguments must conform to this JSON Schema:\n{json.dumps(schema, indent=2)}"
        for name, description, schema in entries
    ]
    names = ", ".join(f"`{name}`" for name, _, _ in entries)
    return (
        f"You must respond by calling exactly one of these {len(entries)} tools: {names}.\n\n"
        + "\n\n".join(blocks)
        + "\n\nReply with a single JSON object and nothing else — no prose, no code fence, "
        "no explanation. The object must name the tool you chose and carry its arguments:\n"
        '{"name": "<one of the tool names above>", "arguments": { ... }}\n'
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

    raise ToolEmulationError(f"model reply was not JSON: {_snippet(text)}")


def parse_emulated_reply(raw: str, tools: list[dict[str, Any]]) -> ToolCall:
    entries = validate_tool_shape(tools)
    by_name = {entry[0]: entry for entry in entries}

    parsed = _extract_json(raw)
    if not isinstance(parsed, dict):
        raise ToolEmulationError(
            f"expected a JSON object, got {type(parsed).__name__}: {_snippet(parsed)}"
        )

    # Some models wrap the payload as {"name": ..., "arguments": {...}}. When they do,
    # the name decides which schema applies — never assume tools[0].
    envelope_name = parsed.get("name")
    if isinstance(envelope_name, str) and isinstance(parsed.get("arguments"), dict):
        if envelope_name not in by_name:
            raise ToolEmulationError(
                f"reply named tool '{envelope_name}', which is not one of the supplied "
                f"tools: {sorted(by_name)}"
            )
        chosen = by_name[envelope_name]
        parsed = parsed["arguments"]
    elif len(entries) > 1:
        raise ToolEmulationError(
            f"{len(entries)} tools were supplied, so the reply must say which one it is "
            'calling using the {"name": ..., "arguments": {...}} form; got keys '
            f"{_keys(parsed)}"
        )
    else:
        chosen = entries[0]

    name, _description, schema = chosen
    for required in schema.get("required", []) or []:
        if required not in parsed:
            raise ToolEmulationError(
                f"reply is missing required property '{required}' for tool '{name}'; "
                f"got keys {_keys(parsed)}"
            )

    return ToolCall(id=f"emulated-{uuid.uuid4().hex[:8]}", name=name, arguments=parsed)
