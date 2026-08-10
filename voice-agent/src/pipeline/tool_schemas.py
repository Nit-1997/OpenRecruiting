"""Turn intake-core tool specs into pipecat FunctionSchemas.

Extracted from factory.py, which read the spec dicts inline at four sites across
two files (build_pipeline's schema construction and its register_function loop,
plus scripts/smoke_test_v2.py). Four inline readers of one wire format is four
places a shape change has to be found by hand, and intake-core's shape is
changing. One named reader with tests is one place.

Deliberately NOT tolerant of multiple shapes. A reader that accepts both the
Anthropic and OpenAI forms would accept a stale spec forever and render it as a
parameterless tool — the model then cannot pass arguments, update_answer records
nothing, and no error is raised anywhere. Refusing an unrecognised spec by name
is the whole point.
"""

from __future__ import annotations

from typing import Any

from pipecat.adapters.schemas.function_schema import FunctionSchema


class UnsupportedToolSchema(ValueError):
    """A tool spec was not in the shape this reader accepts."""


def _body(spec: dict[str, Any]) -> dict[str, Any]:
    """The OpenAI `function` body, or a refusal naming what arrived.

    Only the OpenAI shape is accepted. Accepting the old Anthropic form too would
    let a stale spec through forever and render it as a parameterless tool, which
    is silent — see this module's docstring.
    """
    function = spec.get("function")
    if spec.get("type") == "function" and isinstance(function, dict) and "name" in function:
        return function
    raise UnsupportedToolSchema(
        f"unrecognised tool spec: keys={sorted(spec)!r}; expected the OpenAI shape "
        "{'type': 'function', 'function': {'name', 'description', 'parameters'}}. "
        "Anthropic-shaped specs using 'input_schema' were retired in phase 4."
    )


def tool_name(spec: dict[str, Any]) -> str:
    return _body(spec)["name"]


def function_schemas(specs: list[dict[str, Any]]) -> list[FunctionSchema]:
    schemas = []
    for spec in specs:
        body = _body(spec)
        parameters = body.get("parameters") or {}
        schemas.append(
            FunctionSchema(
                name=body["name"],
                description=body.get("description", ""),
                properties=parameters.get("properties", {}),
                required=parameters.get("required", []),
            )
        )
    return schemas
