"""Tests for the streaming seam both agent loops run through.

The seam does no format translation — llm_core.stream_turn was written to the
tagged contract this codebase already had. What is tested here is the two
normalizations it adds, because both are silent-correctness bugs when absent:

* an emulated alias yields NO tool_call event at all (llm_core client.py:320-334),
  so a tool loop would run to completion having executed nothing;
* stream_turn passes the provider's tool-call id through raw, and it can be None
  (client.py:384/386/458) — which becomes an invalid tool_call_id on the NEXT
  request, i.e. a 400 after the user has already seen text stream in.

Everything here goes through llm-core's FakeLLM, whose stream_turn shares a
signature with the real client (llm-core/tests/test_fake.py asserts it), so a
test cannot pass here and fail against the gateway.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from llm_core.errors import ToolEmulationError
from llm_core.settings import get_settings
from llm_core.types import LLMReply, ToolCall

from app.services.intake.llm_stream import (
    EmulatedToolsNotStreamable,
    stream_llm_turn,
)

pytestmark = pytest.mark.asyncio

_TOOL = {
    "type": "function",
    "function": {
        "name": "update_answer",
        "description": "Record an answer.",
        "parameters": {"type": "object", "properties": {"qid": {"type": "string"}}},
    },
}

# The aliases whose workloads are tool loops. Both MUST resolve to a
# tool-capable model; see test_the_streaming_aliases_declare_native_tool_support.
_STREAMING_ALIASES = ("intake-text", "debrief-chat")

# `make test` mounts only backend/ at /app, so the repo root is not reachable
# from inside the container. Dockerfile.test bakes the config in at /.
_CONFIG_PATHS = (
    Path("/litellm-config.yaml"),                                  # baked into the test image
    Path(__file__).resolve().parents[4] / "litellm-config.yaml",   # repo checkout
)


def _load_gateway_config() -> dict:
    for path in _CONFIG_PATHS:
        if path.exists():
            return yaml.safe_load(path.read_text())
    raise AssertionError(f"litellm-config.yaml not found at any of {_CONFIG_PATHS}")


@pytest.fixture
def forced_json(monkeypatch):
    """Drive LLM_FORCE_JSON_TOOLS despite get_settings() being lru_cached.

    The phase-2 report recorded the absence of a reset hook as a blocker for
    exactly this kind of test. lru_cache exposes cache_clear(), which is enough:
    clear before so the new env is read, and clear after so no later test in the
    session inherits it.
    """

    def _set(value: str):
        monkeypatch.setenv("LLM_FORCE_JSON_TOOLS", value)
        get_settings.cache_clear()

    yield _set
    get_settings.cache_clear()


async def _collect(gen):
    return [ev async for ev in gen]


async def test_events_and_alias_pass_through_unchanged(fake_llm):
    fake_llm.queue_text_deltas("Hello ", "there")
    events = await _collect(
        stream_llm_turn(
            fake_llm,
            model="intake-text",
            system="SYS",
            messages=[{"role": "user", "content": "hi"}],
            tools=[_TOOL],
        )
    )

    assert [k for k, _ in events] == ["text", "text", "done"]
    assert [p for k, p in events if k == "text"] == ["Hello ", "there"]
    call = fake_llm.calls[0]
    assert call["model"] == "intake-text"
    assert call["system"] == "SYS"
    assert call["streaming"] is True


async def test_done_carries_the_providers_finish_reason_verbatim(fake_llm):
    """The value is OpenAI vocabulary, NOT Anthropic's. This is spec reason 1 for
    the rewrite: any consumer comparing against "tool_use" is already broken."""
    fake_llm.queue_tool_call("update_answer", {"qid": "q1"})
    events = await _collect(
        stream_llm_turn(
            fake_llm, model="intake-text", system="S", messages=[], tools=[_TOOL]
        )
    )

    done = [p for k, p in events if k == "done"][0]
    assert done["stop_reason"] == "tool_calls"
    assert done["stop_reason"] != "tool_use"


async def test_tool_call_payload_uses_input_not_arguments(fake_llm):
    fake_llm.queue_tool_call("update_answer", {"qid": "q4_must_haves"})
    events = await _collect(
        stream_llm_turn(
            fake_llm, model="intake-text", system="S", messages=[], tools=[_TOOL]
        )
    )

    call = [p for k, p in events if k == "tool_call"][0]
    assert set(call) == {"id", "name", "input"}
    assert call["input"] == {"qid": "q4_must_haves"}


async def test_an_anthropic_shaped_tool_spec_is_rejected(fake_llm):
    """The migration mistake this phase is most likely to leave behind. FakeLLM
    runs the same validate_tool_shape the gateway path runs, so it fails here
    rather than as an opaque provider 400."""
    fake_llm.queue_text("never reached")
    with pytest.raises(ToolEmulationError) as exc:
        await _collect(
            stream_llm_turn(
                fake_llm,
                model="intake-text",
                system="S",
                messages=[],
                tools=[{"name": "update_answer", "input_schema": {"type": "object"}}],
            )
        )
    assert "input_schema" in str(exc.value)


async def test_an_empty_tool_list_is_sent_as_none(fake_llm):
    """The opening greeting passes tools=[]. `if tools:` in stream_turn treats []
    and None identically, and normalizing here keeps the recorded call unambiguous."""
    fake_llm.queue_text("Hey there")
    await _collect(
        stream_llm_turn(
            fake_llm, model="intake-text", system="S", messages=[], tools=[]
        )
    )
    assert fake_llm.calls[0]["tools"] is None


async def test_an_emulated_alias_is_refused_when_tools_are_supplied(
    fake_llm, forced_json
):
    """stream_turn emits no tool_call event on the emulated path, so a tool loop
    would complete having executed nothing and would stream the emulated JSON to
    the user as prose. Refuse the configuration instead of degrading."""
    forced_json("intake-text,gemma-local")
    with pytest.raises(EmulatedToolsNotStreamable) as exc:
        await _collect(
            stream_llm_turn(
                fake_llm, model="intake-text", system="S", messages=[], tools=[_TOOL]
            )
        )
    assert "intake-text" in str(exc.value)
    assert fake_llm.calls == []


async def test_an_emulated_alias_is_allowed_when_no_tools_are_supplied(
    fake_llm, forced_json
):
    """run_text_opening streams a greeting with tools=[]. Nothing is emulated on
    a request that carries no tools, so refusing it would be wrong."""
    forced_json("intake-text")
    fake_llm.queue_text("Hey there")
    events = await _collect(
        stream_llm_turn(
            fake_llm, model="intake-text", system="S", messages=[], tools=[]
        )
    )
    assert [k for k, _ in events][-1] == "done"


async def test_a_tool_call_with_no_id_is_backfilled(fake_llm):
    """stream_turn yields slot["id"] raw and it is None when the gateway never
    sent one. Both runners put that value in tool_call_id on the NEXT request,
    where OpenAI requires a string — a 400 one turn later."""
    fake_llm.queue_reply(
        LLMReply(
            text="",
            model="fake",
            tool_calls=[ToolCall(id="", name="update_answer", arguments={"qid": "q1"})],
            finish_reason="tool_calls",
        )
    )
    events = await _collect(
        stream_llm_turn(
            fake_llm, model="intake-text", system="S", messages=[], tools=[_TOOL]
        )
    )
    call = [p for k, p in events if k == "tool_call"][0]
    assert call["id"]
    assert "update_answer" in call["id"]


async def test_backfilled_ids_are_distinct_within_a_turn(fake_llm):
    fake_llm.queue_reply(
        LLMReply(
            text="",
            model="fake",
            tool_calls=[
                ToolCall(id="", name="update_answer", arguments={"qid": "q1"}),
                ToolCall(id="", name="update_answer", arguments={"qid": "q2"}),
            ],
            finish_reason="tool_calls",
        )
    )
    events = await _collect(
        stream_llm_turn(
            fake_llm, model="intake-text", system="S", messages=[], tools=[_TOOL]
        )
    )
    ids = [p["id"] for k, p in events if k == "tool_call"]
    assert len(ids) == len(set(ids)) == 2


async def test_a_real_id_is_never_rewritten(fake_llm):
    fake_llm.queue_tool_call("update_answer", {"qid": "q1"})
    events = await _collect(
        stream_llm_turn(
            fake_llm, model="intake-text", system="S", messages=[], tools=[_TOOL]
        )
    )
    assert [p for k, p in events if k == "tool_call"][0]["id"] == "fake-update_answer"


@pytest.mark.asyncio(loop_scope="function")
async def test_the_streaming_aliases_declare_native_tool_support():
    """The OTHER way an alias becomes emulated: model_info in the proxy config.

    llm-core exposes no public capability accessor (CapabilityCache is reachable
    only through the private LLMClient._caps), so this cannot be checked at
    runtime without a private attribute read. Checking the config statically is
    the cheapest place it can fail, and it fails the moment someone points a
    streaming workload at Gemma — which would silently stop the intake agent
    persisting any answer at all.
    """
    config = _load_gateway_config()
    by_name = {entry["model_name"]: entry for entry in config["model_list"]}
    for alias in _STREAMING_ALIASES:
        assert alias in by_name, f"{alias} is not defined in litellm-config.yaml"
        info = by_name[alias].get("model_info") or {}
        assert info.get("supports_function_calling") is True, alias
