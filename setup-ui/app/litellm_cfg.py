"""Read and edit litellm-config.yaml — one model per task.

This file is what the whole LLM gateway migration was for: 27 named workloads,
each independently repointable at a different model or provider. Surfacing it is
the difference between "you can change the model" and "you can change the model
if you know YAML and which of 27 aliases the screening agent uses".

Written LINE-BASED for the same reason as envfile.py, and more urgently: this
file carries dense load-bearing comments — which aliases send tools, why the
OpenAI deployment must drop `temperature`, which tier an alias has to preserve.
A yaml.safe_load/dump round-trip deletes every one of them. Reading uses the
YAML parser; writing touches exactly the one `model:` line being changed.

Two properties the UI has to surface, both learned in production:

  * an alias that SENDS TOOLS must keep `supports_function_calling: true`.
    A false there DISABLES that agent rather than degrading it — streaming and
    emulated tools do not compose, so the JSON arrives as prose and is never
    parsed into a tool call, silently.
  * an OpenAI reasoning model needs `additional_drop_params: ["temperature"]`,
    because nine call sites send temperature=0 and GPT-5 accepts only the
    default. Global `drop_params` does not help: the param IS supported, only
    the value is rejected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

_ALIAS_LINE = re.compile(r"^(\s*)-\s+model_name:\s*(\S+)\s*$")
_MODEL_LINE = re.compile(r"^(\s*)model:\s*(\S+)\s*$")


@dataclass(frozen=True)
class Alias:
    name: str
    model: str
    provider: str
    supports_tools: bool
    drops_temperature: bool
    description: str


def read_aliases(text: str) -> list[Alias]:
    """Every alias, with the comment block above it as its description.

    The comments are the only place recording WHY an alias is pinned to a tier,
    so they are carried through to the UI rather than left in a file nobody
    opens.
    """
    data = yaml.safe_load(text) or {}
    descriptions = _descriptions(text)

    out: list[Alias] = []
    for entry in data.get("model_list", []) or []:
        name = entry.get("model_name")
        if not name:
            continue
        params = entry.get("litellm_params") or {}
        model = str(params.get("model", ""))
        info = entry.get("model_info") or {}
        out.append(
            Alias(
                name=name,
                model=model,
                provider=model.split("/")[0] if "/" in model else "",
                supports_tools=bool(info.get("supports_function_calling")),
                drops_temperature="temperature" in (params.get("additional_drop_params") or []),
                description=descriptions.get(name, ""),
            )
        )
    return out


def _descriptions(text: str) -> dict[str, str]:
    """The contiguous comment block immediately above each `- model_name:`."""
    result: dict[str, str] = {}
    buffer: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        match = _ALIAS_LINE.match(line)
        if match:
            result[match.group(2)] = " ".join(buffer).strip()
            buffer = []
        elif stripped.startswith("#"):
            # Section headings in this file are written as "── Heading ──────",
            # so strip the rule characters off both ends rather than only
            # skipping lines made entirely of them — otherwise the box drawing
            # ends up in the UI.
            cleaned = stripped.lstrip("#").strip().strip("─—-=").strip()
            if cleaned:
                buffer.append(cleaned)
        elif not stripped:
            buffer = []
        elif not stripped.startswith("-") and ":" in stripped:
            # A property line inside the previous entry; its comments are not a
            # description of the NEXT alias.
            buffer = []
    return result


def set_model(text: str, alias: str, new_model: str) -> str:
    """Repoint one alias, changing exactly one line.

    Raises LookupError when the alias or its `model:` line is not found, rather
    than appending something plausible — a silently added alias would be served
    by the gateway and never noticed.
    """
    lines = text.splitlines()
    start = None
    indent = ""
    for i, line in enumerate(lines):
        match = _ALIAS_LINE.match(line)
        if match and match.group(2) == alias:
            start, indent = i, match.group(1)
            break
    if start is None:
        raise LookupError(f"No alias named '{alias}' in litellm-config.yaml")

    for i in range(start + 1, len(lines)):
        # Stop at the next alias so we can never edit a neighbour's model line.
        nxt = _ALIAS_LINE.match(lines[i])
        if nxt and len(nxt.group(1)) <= len(indent):
            break
        model_match = _MODEL_LINE.match(lines[i])
        if model_match:
            lines[i] = f"{model_match.group(1)}model: {new_model}"
            result = "\n".join(lines)
            return result + "\n" if text.endswith("\n") else result

    raise LookupError(f"Alias '{alias}' has no model: line to change")
