"""Prove the gateway serves a LOCAL model on both dispatch paths.

Spec acceptance #3 (docs/superpowers/specs/2026-08-07-provider-agnostic-llm-design.md
§Testing) asks for a documented check that flips aliases to a local model and
exercises "one non-tool site and one tool-using site end to end, proving both the
native and emulated paths". The Makefile target used to POST one bare chat
completion and print the reply, which proved neither.

The tool-using half is the half that matters. `gemma-local` is declared
`supports_function_calling: false`, so llm_core takes its EMULATION path: the
tool schema is rendered into the prompt and the reply is parsed back into a
ToolCall. That code is the reason llm-core has an emulation module at all, and
until now nothing in any acceptance gate ran it.

Deliberately uses complete() for BOTH halves, never stream_turn. Streaming and
emulated tools do not compose — on an alias without native tool support
stream_turn emits no tool_call event at all and yields the emulated JSON as
prose. Testing the tool half through stream_turn would "pass" while proving the
opposite of what it claims.

Run via `make verify-local-llm`. Exits non-zero on any failure so it can gate.
"""

from __future__ import annotations

import asyncio
import sys

from llm_core import get_client

# Both are ollama_chat/gemma4 with supports_function_calling: false.
_NON_TOOL_ALIAS = "gemma-local"
_TOOL_ALIAS = "intake-jd-local"

_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_job_title",
        "description": "Emit the job title found in the text.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "The job title."},
            },
            "required": ["title"],
        },
    },
}


def _report(label: str, ok: bool, detail: str) -> bool:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label:<34} {detail}")
    return ok


async def main() -> int:
    llm = get_client()
    results: list[bool] = []

    print("Local model through the gateway — both dispatch paths")

    # 1. Non-tool path: a plain completion. This is the shape the coverage
    #    tracker and the screening assessor use — prose in, prose out.
    try:
        reply = await llm.complete(
            model=_NON_TOOL_ALIAS,
            max_tokens=32,
            system="Answer with one word only.",
            messages=[{"role": "user", "content": "Say the word ready."}],
        )
        text = (reply.text or "").strip()
        results.append(
            _report("non-tool completion", bool(text), f"reply={text[:40]!r}")
        )
    except Exception as exc:  # noqa: BLE001 — this is the gate; report and fail
        results.append(_report("non-tool completion", False, f"{type(exc).__name__}: {exc}"))

    # 2. Emulated tool path: the alias declares no native function calling, so
    #    llm_core renders the schema into the prompt and parses the reply back
    #    into a ToolCall. A local model is genuinely worse at this than a
    #    frontier one — that is the point. If this breaks, every local-model
    #    tool site breaks silently.
    try:
        reply = await llm.complete(
            model=_TOOL_ALIAS,
            max_tokens=200,
            system="Extract the job title. Respond ONLY by calling emit_job_title.",
            tools=[_TOOL],
            messages=[
                {
                    "role": "user",
                    "content": "We are hiring a Senior Backend Engineer in Berlin.",
                }
            ],
        )
        call = reply.tool_call_named("emit_job_title")
        ok = call is not None and isinstance(call.arguments, dict) and "title" in call.arguments
        detail = (
            f"tool={call.name} args={call.arguments}"
            if call is not None
            else f"NO TOOL CALL (finish={reply.finish_reason}, text={(reply.text or '')[:60]!r})"
        )
        results.append(_report("emulated tool call", ok, detail))
    except Exception as exc:  # noqa: BLE001
        results.append(_report("emulated tool call", False, f"{type(exc).__name__}: {exc}"))

    print()
    if all(results):
        print("BOTH PATHS OK — the gateway serves a local model with and without tools.")
        return 0
    print("FAILED — see above. A local-model deployment would be broken on that path.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
