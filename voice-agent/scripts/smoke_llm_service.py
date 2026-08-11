"""Exercise the REAL pipecat LLM service against the REAL gateway.

Run inside the built container, where pipecat is actually installed:

    docker compose run --rm -v "$PWD/voice-agent/scripts:/app/scripts" \
        voice-agent python /app/scripts/smoke_llm_service.py

(`scripts/` is not baked into the image — voice-agent/Dockerfile copies `src/`
only — so it has to be mounted.)

Why this file exists. voice-agent's unit suite stubs pipecat into sys.modules,
so it CANNOT fail on a pipecat incompatibility — every FunctionSchema,
ToolsSchema and OpenAILLMService under test is a MagicMock. And
factory.create_pipeline runs only when a WebRTC peer connects, so `make verify`
cannot fail on one either: /health stays green with a completely broken
constructor. Between those two blind spots sits the entire gateway migration.
This script closes the gap for everything except audio: it builds the service
the factory builds, hands it the tool specs the factory hands it, asks pipecat's
own adapter to render the request, and sends exactly that request to the gateway.

What it does NOT cover, and must not be claimed to: WebRTC transport, STT/TTS,
interruption, and turn timing. Only a live voice session covers those.
"""

from __future__ import annotations

import asyncio
import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, ".")


async def main() -> int:
    from intake_core.tools import INTAKE_TOOLS
    from pipecat.adapters.schemas.tools_schema import ToolsSchema
    from pipecat.processors.aggregators.llm_context import LLMContext

    from src.config import get_settings
    from src.pipeline.services import create_llm
    from src.pipeline.tool_schemas import function_schemas, tool_name

    settings = get_settings()

    print("[0] Provider SDK must be absent from this image...")
    try:
        import anthropic  # noqa: F401

        print(f"    FAIL: anthropic {anthropic.__version__} is still installed. "
              "requirements.txt must not carry pipecat's [anthropic] extra.")
        return 1
    except ModuleNotFoundError:
        print("    ok — import anthropic raises ModuleNotFoundError")

    print("[1] Constructing the service the factory constructs...")
    llm = create_llm(
        api_key=settings.litellm_master_key,
        model=settings.voice_intake_model,
        base_url=settings.llm_gateway_url + "/v1",
    )
    print(f"    {type(llm).__module__}.{type(llm).__name__}  model={llm.model_name}")
    print(f"    base_url={settings.llm_gateway_url + '/v1'}")

    print("[2] Building the context the factory builds...")
    messages = [
        {"role": "system", "content": "You are Scout. Record what the recruiter tells you."},
        {"role": "user", "content": "The role is a Staff Backend Engineer on the payments team."},
    ]
    tools_schema = ToolsSchema(standard_tools=function_schemas(INTAKE_TOOLS))
    context = LLMContext(messages, tools=tools_schema)

    print("[3] Registering the tool handlers the factory registers...")
    seen: list[str] = []

    async def _probe(params):
        seen.append(params.function_name)
        await params.result_callback({"ok": True})

    for spec in INTAKE_TOOLS:
        llm.register_function(tool_name(spec), _probe)
    print(f"    registered: {sorted(n for n in llm._functions if n)}")

    print("[4] Rendering the request through pipecat's own adapter...")
    params_from_context = llm.get_llm_adapter().get_llm_invocation_params(context)
    request = llm.build_chat_completion_params(params_from_context)
    tools = request.get("tools") or []
    if not tools:
        print("    FAIL: the adapter produced no tools — the pipeline would be toolless")
        return 1
    for tool in tools:
        fn = tool["function"]
        if not fn["parameters"].get("properties"):
            print(f"    FAIL: {fn['name']} reached pipecat with NO properties")
            return 1
        if not fn["parameters"].get("required"):
            print(f"    FAIL: {fn['name']} reached pipecat with NO required list")
            return 1
    print(f"    model={request['model']}  tools={[t['function']['name'] for t in tools]}")
    print(f"    max_tokens={request.get('max_tokens')!r}  "
          f"(NOT_GIVEN is deliberate — see create_llm's docstring)")

    print("[5] One live streaming call through the gateway...")
    saw_tool, saw_text, arguments = False, False, ""
    stream = await llm.get_chat_completions(params_from_context)
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta and delta.tool_calls:
            saw_tool = True
            call = delta.tool_calls[0]
            if call.function and call.function.arguments:
                arguments += call.function.arguments
        elif delta and delta.content:
            saw_text = True
    print(f"    saw_tool_call={saw_tool} saw_text={saw_text} arg_chars={len(arguments)}")

    if not saw_tool:
        print("FAIL: the alias returned no tool call. Either it is not tool-capable "
              "through the gateway, or the tool payload was rejected. This is the "
              "failure the unit suite cannot see.")
        return 1

    parsed = json.loads(arguments) if arguments else {}
    print(f"    arguments parsed: {parsed}")
    if not parsed:
        print("WARN: the tool call arrived with EMPTY arguments. OpenAILLMService "
              "DROPS such a call before any handler runs (pipecat "
              "openai/base_llm.py:464) — and because the append and the dispatch "
              "share one branch, it discards every other tool call in the turn "
              "too. src/pipeline/empty_turn.py is what makes that audible.")

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
