"""Live checks against a running gateway. Excluded from default runs.

Run with:

    cd llm-core
    LITELLM_MASTER_KEY=$(grep '^LITELLM_MASTER_KEY=' ../.env | cut -d= -f2-) \
    LLM_GATEWAY_URL=http://localhost:4000 \
        python -m pytest tests/integration -m live_gateway -v

Only the gateway key is needed here — the provider keys stay inside the litellm
container, which is the entire point of the gateway. Do not `source ../.env`: it
holds a multi-line PEM and the shell chokes on it.

Requires: `docker compose up -d litellm`, plus `ollama serve` with `gemma4:latest`
pulled for the `smoke-local` alias.

These tests spend real money on the two hosted aliases. The suite is deliberately
twelve model calls with small `max_tokens` and no retry loops — do not add
parametrizations or reruns without re-counting the calls.

What each alias resolves to lives in `litellm-config.yaml`; the point of the
aliases is that this file never names a provider.
"""

from __future__ import annotations

import os
from typing import Iterator

import pytest

from llm_core.client import LLMClient
from llm_core.emulation import parse_emulated_reply
from llm_core.settings import get_settings

pytestmark = pytest.mark.live_gateway

# One alias per provider the gateway fronts. `smoke-local` is declared
# supports_function_calling: false, so it exercises the JSON emulation path.
#
# OVERRIDABLE, because this suite is the only place that measures whether a model
# can really do the four things every workload needs — text, native tools with
# typed arguments, streaming, and multi-tool routing. Pointing it at a candidate
# model is how "can we run on this?" gets an answer instead of an opinion, and
# hardcoding the list meant re-editing the file to ask. The DEFAULTS are
# unchanged, so the cost note in this module's docstring still describes what a
# plain run spends; an override is opt-in and pays for its own calls.
#
#   LIVE_HOSTED_ALIASES=or-qwen,or-glm LIVE_LOCAL_ALIAS= python -m pytest ...
#
# An empty LIVE_LOCAL_ALIAS skips the emulation tests rather than failing them,
# for runs on a host with no Ollama.
HOSTED_ALIASES = [
    a.strip()
    for a in os.environ.get(
        "LIVE_HOSTED_ALIASES", "smoke-anthropic,smoke-openai"
    ).split(",")
    if a.strip()
]
LOCAL_ALIAS = os.environ.get("LIVE_LOCAL_ALIAS", "smoke-local").strip()
ALL_ALIASES = [*HOSTED_ALIASES, *([LOCAL_ALIAS] if LOCAL_ALIAS else [])]

requires_local = pytest.mark.skipif(
    not LOCAL_ALIAS, reason="LIVE_LOCAL_ALIAS is empty; no local model to emulate against"
)

JD_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_job_description",
        "description": "Return the structured job description.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "location": {"type": "string"},
            },
            "required": ["title"],
        },
    },
}

CANDIDATE_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_candidate_profile",
        "description": "Return the structured profile of a job applicant.",
        "parameters": {
            "type": "object",
            "properties": {
                "full_name": {"type": "string"},
                "headline": {"type": "string"},
            },
            "required": ["full_name"],
        },
    },
}

JOB_PROMPT = "Job opening: Staff SRE, based in Remote - US. Record it."


def _record(label: str, value: object) -> None:
    """Print an observation so `-s` runs leave evidence of real model behaviour.

    Test prompts only; nothing here carries a key or customer data.
    """
    print(f"\n[live] {label}: {value!r}")


@pytest.fixture(scope="module", autouse=True)
def _gateway_env() -> Iterator[None]:
    """Point llm_core at the local gateway and drop the memoized settings.

    Module-scoped and using os.environ rather than monkeypatch: monkeypatch is
    function-scoped, and a higher-scoped fixture would otherwise be built before
    it ran.
    """
    if not os.environ.get("LITELLM_MASTER_KEY"):
        # Skipped rather than failed: without the gateway key every call is a 401,
        # and "you forgot to export the key" is more useful than twelve auth errors.
        pytest.skip("LITELLM_MASTER_KEY is not set; see this module's docstring")
    os.environ.setdefault("LLM_GATEWAY_URL", "http://localhost:4000")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> LLMClient:
    """A fresh client per test.

    Per-test rather than shared: AsyncOpenAI opens its connection pool on the
    running loop, and pytest-asyncio gives each test its own. The cost is one
    extra `/model/info` GET per test, which is free and is itself part of what
    this suite proves.
    """
    return LLMClient()


# --------------------------------------------------------------------------
# Plain text, every provider
# --------------------------------------------------------------------------


@pytest.mark.parametrize("alias", ALL_ALIASES)
async def test_alias_returns_text(client: LLMClient, alias: str) -> None:
    reply = await client.complete(
        model=alias,
        messages=[{"role": "user", "content": "Reply with the single word: ready"}],
        max_tokens=64,
    )

    _record(f"{alias} text", reply.text)
    assert reply.text.strip() != ""
    assert reply.emulated_tools is False
    if alias in HOSTED_ALIASES:
        assert "ready" in reply.text.lower()


# --------------------------------------------------------------------------
# Tool calling: native on the hosted aliases, emulated on the local one
# --------------------------------------------------------------------------


@pytest.mark.parametrize("alias", HOSTED_ALIASES)
async def test_native_tool_call_returns_typed_arguments(
    client: LLMClient, alias: str
) -> None:
    reply = await client.complete(
        model=alias,
        messages=[{"role": "user", "content": JOB_PROMPT}],
        tools=[JD_TOOL],
        max_tokens=256,
    )

    _record(f"{alias} native tool", [(c.name, c.arguments) for c in reply.tool_calls])
    assert reply.emulated_tools is False

    call = reply.tool_call_named("emit_job_description")
    assert call is not None
    assert isinstance(call.arguments, dict)
    # The gateway hands arguments back as a JSON string; the client decodes it.
    # A str here would mean the decode was skipped and every caller would be
    # indexing into characters.
    assert isinstance(call.arguments.get("title"), str)
    assert "SRE" in call.arguments["title"]


@requires_local
async def test_local_tool_call_is_emulated_and_carries_required_property(
    client: LLMClient,
) -> None:
    reply = await client.complete(
        model=LOCAL_ALIAS,
        messages=[{"role": "user", "content": JOB_PROMPT}],
        tools=[JD_TOOL],
        max_tokens=256,
    )

    _record(
        f"{LOCAL_ALIAS} emulated tool",
        [(c.name, c.arguments) for c in reply.tool_calls],
    )
    assert reply.emulated_tools is True

    call = reply.tool_call_named("emit_job_description")
    assert call is not None
    # Presence alone proves nothing here: parse_emulated_reply already raises when
    # a required property is missing, and _to_reply always returns exactly one
    # call, so `call is not None` and `"title" in call.arguments` are both
    # structurally guaranteed the moment complete() returns. Emulation validation
    # is presence-only by design, so {"title": null} and {"title": 42} would also
    # satisfy the schema. Assert the same thing the hosted path asserts — that the
    # local model actually extracted the role — or this test cannot tell a working
    # local path from a model emitting a null.
    assert isinstance(call.arguments.get("title"), str)
    assert "SRE" in call.arguments["title"]


# --------------------------------------------------------------------------
# Streaming
# --------------------------------------------------------------------------


@pytest.mark.parametrize("alias", HOSTED_ALIASES)
async def test_streaming_yields_text_deltas_and_a_terminal_done(
    client: LLMClient, alias: str
) -> None:
    events: list[tuple[str, object]] = []
    async for event in client.stream_turn(
        model=alias,
        messages=[{"role": "user", "content": "Count from one to five, in words."}],
        max_tokens=64,
    ):
        events.append(event)

    kinds = [kind for kind, _ in events]
    _record(f"{alias} stream kinds", kinds)

    assert kinds[-1] == "done"
    assert kinds.count("done") == 1
    text_deltas = [payload for kind, payload in events if kind == "text"]
    assert text_deltas, "no text deltas arrived"
    assert all(isinstance(delta, str) for delta in text_deltas)

    done = events[-1][1]
    assert isinstance(done, dict)
    _record(f"{alias} stream done", done)
    assert done["text"] == "".join(text_deltas)
    assert done["text"].strip() != ""


@requires_local
async def test_streaming_with_emulated_tools_yields_text_not_tool_calls(
    client: LLMClient,
) -> None:
    """Streaming and emulated tools do not compose. This pins down both halves.

    `stream_turn` pushes the tool schema into a system message for a model with
    no native tool support, but never parses the reply back — the emulated JSON
    arrives as ('text', ...) prose and no ('tool_call', ...) is emitted. A caller
    needing both must use `complete()`. Documented in `LLMClient.stream_turn`.

    The negative half (no tool_call) is cheap to assert and worth little on its
    own: a `stream_turn` that silently dropped the emulation injection entirely
    would pass it too, while returning unusable prose. So the positive half is
    asserted as well, by feeding the streamed text to the very parser
    `complete()` would have used. That it round-trips into the expected ToolCall
    is what makes "the JSON arrives as text, only the parse is missing" a claim
    rather than a hope.
    """
    events: list[tuple[str, object]] = []
    async for event in client.stream_turn(
        model=LOCAL_ALIAS,
        messages=[{"role": "user", "content": JOB_PROMPT}],
        tools=[JD_TOOL],
        max_tokens=256,
    ):
        events.append(event)

    kinds = [kind for kind, _ in events]
    _record(f"{LOCAL_ALIAS} stream kinds", sorted(set(kinds)))

    assert kinds[-1] == "done"
    assert "tool_call" not in kinds
    done = events[-1][1]
    assert isinstance(done, dict)
    _record(f"{LOCAL_ALIAS} stream done text", done["text"])
    assert done["text"].strip() != ""

    # Note this is NOT a substring check for the tool name: with a single tool the
    # emulation instruction names it in the prompt and asks for the bare arguments
    # object back, so the reply legitimately never mentions `emit_job_description`.
    # Round-tripping through the real parser is the assertion that holds.
    recovered = parse_emulated_reply(done["text"], [JD_TOOL])
    _record(f"{LOCAL_ALIAS} stream text reparsed", (recovered.name, recovered.arguments))
    assert recovered.name == "emit_job_description"
    assert isinstance(recovered.arguments.get("title"), str)
    assert "SRE" in recovered.arguments["title"]


# --------------------------------------------------------------------------
# Multi-tool routing
# --------------------------------------------------------------------------


@pytest.mark.parametrize("alias", HOSTED_ALIASES)
async def test_multi_tool_routing_selects_the_right_tool(
    client: LLMClient, alias: str
) -> None:
    reply = await client.complete(
        model=alias,
        messages=[{"role": "user", "content": JOB_PROMPT}],
        tools=[CANDIDATE_TOOL, JD_TOOL],
        max_tokens=256,
    )

    names = [call.name for call in reply.tool_calls]
    _record(f"{alias} multi-tool names", names)
    assert reply.tool_call_named("emit_job_description") is not None
    assert reply.tool_call_named("emit_candidate_profile") is None


@requires_local
async def test_local_multi_tool_routing_selects_the_right_tool(
    client: LLMClient,
) -> None:
    """The local model must name its choice in the {"name", "arguments"} envelope.

    With more than one tool, `parse_emulated_reply` refuses to guess which schema
    applies, so a model that answers with bare arguments raises rather than
    returning a call attributed to the wrong tool.
    """
    reply = await client.complete(
        model=LOCAL_ALIAS,
        messages=[{"role": "user", "content": JOB_PROMPT}],
        tools=[CANDIDATE_TOOL, JD_TOOL],
        max_tokens=256,
    )

    names = [call.name for call in reply.tool_calls]
    _record(f"{LOCAL_ALIAS} multi-tool names", names)
    assert reply.emulated_tools is True
    assert reply.tool_call_named("emit_job_description") is not None
