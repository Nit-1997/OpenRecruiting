"""The streaming seam both agent loops run through.

Replaces anthropic_stream.py. The tagged event contract is UNCHANGED —
('text', str) | ('tool_call', {id, name, input}) | ('done', {text, stop_reason})
— because llm_core.stream_turn was deliberately written to it
(llm-core/llm_core/client.py:275-282, "Contract copied from the Anthropic-era
wrapper so consumers do not change"). This module therefore performs no format
translation at all. What it adds is the two normalizations a bare passthrough
would leave to every caller, both of which are silent-correctness bugs when
forgotten, plus the single seam the runner tests patch.

1. REFUSING AN EMULATED ALIAS. On an alias without native function calling,
   stream_turn pushes the tool schema into a system message and never parses the
   reply back — no tool_call event is emitted at all (client.py:320-334, and its
   docstring says so in as many words). Both callers of this module are tool
   loops: the intake runner would silently never persist a recruiter's answer,
   and the debrief runner would answer over no retrieved data with no action
   proposable. The emulated JSON would additionally be streamed to the user as
   chat prose. There is no error and no failing request anywhere in that, so the
   configuration is refused rather than degraded.

   This covers the LLM_FORCE_JSON_TOOLS override only. The other route to an
   emulated alias is `model_info: {supports_function_calling: false}` in
   litellm-config.yaml, which llm-core exposes no public accessor for; that one
   is pinned statically by test_llm_stream.py.

2. BACKFILLING A MISSING TOOL-CALL ID. stream_turn yields slot["id"] verbatim,
   and it is None whenever the gateway did not echo an id (client.py:384, 386,
   458). Both callers write that value into `tool_call_id` on the FOLLOWING
   request, where OpenAI requires a string. A None there is a provider 400 one
   turn later — after the user has already watched text stream in.

stop_reason in the done event is the provider's finish_reason passed through
untouched, so it speaks OpenAI's vocabulary ("stop", "tool_calls", "length").
Neither loop branches on it; both are driven by whether tool calls arrived. That
is deliberate — see text_runner.run_text_turn.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import structlog
from llm_core.settings import get_settings

logger = structlog.get_logger(__name__)


class EmulatedToolsNotStreamable(RuntimeError):
    """A tool-using stream was pointed at an alias whose tools would be emulated.

    Not an LLMError: nothing reached a provider, and this is a configuration bug
    in this deployment rather than a provider failure. Raising a distinct type
    keeps it out of the `except LLMError` handlers that treat provider trouble as
    transient and retryable — this one will never succeed on a retry.
    """


async def stream_llm_turn(
    llm,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    max_tokens: int = 2048,
) -> AsyncIterator[tuple[str, Any]]:
    """Stream a single assistant turn as tagged events.

    ('text', str)        — incremental prose chunk. SEVERAL per turn; consumers
                           must accumulate and may not assume one event.
    ('tool_call', {...}) — a completed call: {id, name, input}. `input`, not
                           `arguments` — the streaming event key differs from the
                           ToolCall field name on the non-streaming path. Emitted
                           only once the argument JSON is fully assembled.
    ('done', {...})      — {text, stop_reason}, exactly once, last.

    `model` is a gateway alias, never a provider model id.
    """
    if tools and model in get_settings().force_json_tools:
        raise EmulatedToolsNotStreamable(
            f"alias {model!r} is listed in LLM_FORCE_JSON_TOOLS, so its tools "
            "would be emulated. llm_core.stream_turn emits no tool_call event on "
            "that path, so this tool loop would run to completion having executed "
            "nothing while streaming the emulated JSON to the user as prose. "
            "Point this workload at a tool-capable alias."
        )

    backfilled = 0
    async for kind, payload in llm.stream_turn(
        model=model,
        system=system,
        messages=messages,
        tools=tools or None,
        max_tokens=max_tokens,
    ):
        if kind == "tool_call" and not payload.get("id"):
            backfilled += 1
            name = payload.get("name")
            # Deterministic and unique within the turn. The caller holds one dict
            # per call and reads its id twice — once for the assistant message's
            # tool_calls entry, once for the matching tool result — so stability
            # matters more than the value.
            payload = {**payload, "id": f"call_{backfilled}_{name}"}
            logger.warning(
                "llm_stream_tool_call_id_backfilled", alias=model, name=name
            )
        yield (kind, payload)
