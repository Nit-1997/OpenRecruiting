"""FakeLLM is the testing contract for the whole migration.

Twenty-six test files across five services stop hand-building Anthropic response
objects and start queueing outcomes here. Every one of them is only as honest as
this double: a fake whose signatures or event shapes have drifted from the real
client lets a migrated test pass against something production can never produce.
The signature-parity tests below exist to make that drift fail loudly.
"""

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from llm_core.client import LLMClient
from llm_core.errors import LLMError, ToolEmulationError
from llm_core.fake import FakeLLM
from llm_core.types import LLMReply, ToolCall


async def test_queued_text_is_returned():
    fake = FakeLLM()
    fake.queue_text("hello")

    reply = await fake.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}])

    assert reply.text == "hello"


async def test_queued_tool_call_is_returned():
    fake = FakeLLM()
    fake.queue_tool_call("emit_job_description", {"title": "SRE"})

    reply = await fake.complete(model="intake-jd", messages=[], tools=[])

    call = reply.tool_call_named("emit_job_description")
    assert call.arguments == {"title": "SRE"}


async def test_records_calls_for_assertions():
    fake = FakeLLM()
    fake.queue_text("ok")

    await fake.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}], system="be terse")

    assert fake.calls[0]["model"] == "intake-jd"
    assert fake.calls[0]["system"] == "be terse"


async def test_queued_error_is_raised():
    fake = FakeLLM()
    fake.queue_error(RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await fake.complete(model="intake-jd", messages=[])


async def test_stream_turn_replays_queued_text_then_done():
    # DEVIATION from the brief, which asserted `("text", "hi there") in events`.
    # queue_text now streams multiple deltas so consumers cannot assume one text
    # event per turn (the real client yields once per content chunk), which makes
    # that assertion false by construction. Asserting on the concatenation is the
    # stronger claim anyway: it holds whatever the split.
    fake = FakeLLM()
    fake.queue_text("hi there")

    events = [e async for e in fake.stream_turn(model="debrief-chat", messages=[])]

    assert "".join(payload for kind, payload in events if kind == "text") == "hi there"
    assert events[-1][0] == "done"
    assert events[-1][1]["text"] == "hi there"


async def test_running_dry_raises_a_clear_error():
    fake = FakeLLM()

    with pytest.raises(AssertionError, match="no queued response"):
        await fake.complete(model="intake-jd", messages=[])


# --- signature parity: the most valuable tests in this file ---------------
#
# Both modules use `from __future__ import annotations`, so annotations compare
# as source strings and this is exact-match strict — a semantically identical
# rewrite of the real client (`Optional[X]` for `X | None`) fails here too. That
# is the intended trade: a false alarm costs one line of edit, a false pass
# costs a 26-file migration written against a lie.


def _public_methods_of_the_real_client() -> list[str]:
    """The parity list is DERIVED, never hardcoded.

    A hardcoded ["complete", "stream_turn"] silently declines to check any method
    added later — the pair could ship with mismatched signatures and this file
    would stay green.
    """
    return sorted(
        name
        for name, _ in inspect.getmembers(LLMClient, inspect.isfunction)
        if not name.startswith("_")
    )


def test_the_parity_list_is_not_empty():
    """If introspection ever returns nothing, every parametrized parity test
    below vacuously passes. Fail loudly instead."""
    assert _public_methods_of_the_real_client(), "found no public methods on LLMClient"


@pytest.mark.parametrize("method", _public_methods_of_the_real_client())
def test_fake_signature_matches_the_real_client(method):
    assert hasattr(FakeLLM, method), (
        f"LLMClient exposes {method!r}, which FakeLLM does not implement"
    )
    real = inspect.signature(getattr(LLMClient, method))
    fake = inspect.signature(getattr(FakeLLM, method))

    assert fake == real, (
        f"FakeLLM.{method} has drifted from LLMClient.{method}.\n"
        f"  real: {real}\n"
        f"  fake: {fake}\n"
        "Migrated tests call the fake with the real client's keywords; a "
        "mismatch means they are testing a call production cannot make."
    )


@pytest.mark.parametrize("method", _public_methods_of_the_real_client())
def test_fake_awaitability_matches_the_real_client(method):
    """inspect.signature is BLIND to async-ness.

    `inspect.signature(async def f(x))` equals `inspect.signature(def f(x))`, so
    signature parity alone would pass a sync fake standing in for an async client
    method — and every migrated test would await something that is not awaitable
    only once it ran against the real thing.
    """
    real = getattr(LLMClient, method)
    fake = getattr(FakeLLM, method)

    assert inspect.iscoroutinefunction(fake) == inspect.iscoroutinefunction(real), (
        f"FakeLLM.{method} coroutine-ness differs from LLMClient.{method}: "
        f"real={inspect.iscoroutinefunction(real)}, fake={inspect.iscoroutinefunction(fake)}"
    )
    assert inspect.isasyncgenfunction(fake) == inspect.isasyncgenfunction(real), (
        f"FakeLLM.{method} async-generator-ness differs from LLMClient.{method}: "
        f"real={inspect.isasyncgenfunction(real)}, fake={inspect.isasyncgenfunction(fake)}"
    )


def test_fake_covers_every_public_method_of_the_real_client():
    """Catches a method ADDED to LLMClient that the fake never grew.

    Signature parity only compares methods the fake already has, so a new
    `LLMClient.embed()` would sail past it and only fail once a service tried to
    substitute the fake for the client.
    """
    missing = set(_public_methods_of_the_real_client()) - set(dir(FakeLLM))

    assert not missing, f"LLMClient exposes {sorted(missing)}, which FakeLLM does not implement"


# --- streaming event shapes ----------------------------------------------


async def test_stream_turn_emits_tool_calls_in_the_clients_event_shape():
    fake = FakeLLM()
    fake.queue_tool_call("emit_job_description", {"title": "SRE"})

    events = [e async for e in fake.stream_turn(model="intake-jd", messages=[], tools=[])]

    kind, payload = events[0]
    assert kind == "tool_call"
    # `input`, not `arguments` — the wire event key differs from the ToolCall
    # field name on the real client, and consumers read the event.
    assert payload == {
        "id": "fake-emit_job_description",
        "name": "emit_job_description",
        "input": {"title": "SRE"},
    }
    assert set(payload) == {"id", "name", "input"}


async def test_stream_turn_done_carries_the_replys_finish_reason():
    fake = FakeLLM()
    fake.queue_tool_call("emit_job_description", {"title": "SRE"})

    events = [e async for e in fake.stream_turn(model="intake-jd", messages=[])]

    assert events[-1] == ("done", {"text": "", "stop_reason": "tool_calls"})


async def test_stream_turn_emits_no_text_event_for_an_empty_reply():
    """The real client only yields ('text', ...) when a delta carried content."""
    fake = FakeLLM()
    fake.queue_reply(LLMReply(text="", model="fake", finish_reason="stop"))

    events = [e async for e in fake.stream_turn(model="debrief-chat", messages=[])]

    assert events == [("done", {"text": "", "stop_reason": "stop"})]


async def test_queued_error_surfaces_from_stream_turn():
    """Async generators do not run until iterated, so the raise lands in the
    consumer's `async for` — exactly where the real client's LLMError lands."""
    fake = FakeLLM()
    fake.queue_error(LLMError("gateway down", alias="debrief-chat"))

    stream = fake.stream_turn(model="debrief-chat", messages=[])

    with pytest.raises(LLMError, match="gateway down"):
        [e async for e in stream]


async def test_stream_turn_records_the_call_and_marks_it_streaming():
    fake = FakeLLM()
    fake.queue_text("hi")

    [e async for e in fake.stream_turn(model="debrief-chat", messages=[], system="be terse")]

    assert fake.calls[0]["model"] == "debrief-chat"
    assert fake.calls[0]["system"] == "be terse"
    assert fake.calls[0]["streaming"] is True
    assert "temperature" not in fake.calls[0]


# --- queue behaviour ------------------------------------------------------


async def test_queue_is_fifo_across_mixed_outcomes():
    fake = FakeLLM()
    fake.queue_text("first")
    fake.queue_tool_call("emit_job_description", {"title": "SRE"})
    fake.queue_error(RuntimeError("third"))

    assert (await fake.complete(model="a", messages=[])).text == "first"
    second = await fake.complete(model="a", messages=[])
    assert second.tool_call_named("emit_job_description") is not None
    with pytest.raises(RuntimeError, match="third"):
        await fake.complete(model="a", messages=[])

    assert len(fake.calls) == 3


async def test_a_call_is_recorded_even_when_it_raises():
    """Assertions about what the code under test sent still work on the failure
    path, which is where a retry or fallback is usually what needs asserting."""
    fake = FakeLLM()
    fake.queue_error(RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await fake.complete(model="intake-jd", messages=[], max_tokens=99)

    assert fake.calls[0]["max_tokens"] == 99


async def test_complete_records_every_argument_the_signature_accepts():
    fake = FakeLLM()
    fake.queue_text("ok")

    await fake.complete(model="intake-jd", messages=[])

    accepted = set(inspect.signature(FakeLLM.complete).parameters) - {"self"}
    assert set(fake.calls[0]) == accepted


# --- the nameless tool call, mirroring the real client --------------------


async def test_complete_rejects_a_queued_nameless_tool_call():
    fake = FakeLLM()
    fake.queue_reply(
        LLMReply(text="", model="fake", tool_calls=[ToolCall(id="1", name="", arguments={})])
    )

    with pytest.raises(LLMError, match="no function name"):
        await fake.complete(model="intake-jd", messages=[])


async def test_stream_turn_rejects_a_queued_nameless_tool_call():
    fake = FakeLLM()
    fake.queue_reply(
        LLMReply(text="", model="fake", tool_calls=[ToolCall(id="1", name="", arguments={})])
    )

    with pytest.raises(LLMError, match="no function name"):
        [e async for e in fake.stream_turn(model="intake-jd", messages=[])]


# --- recorded calls are snapshots, not references -------------------------
#
# The real client does `outgoing = list(messages)` before it touches anything.
# `calls` is this double's entire assertion surface, and multi-turn tool loops —
# the dominant pattern across the five migrating services — mutate the very list
# they passed in. Storing the reference would let a turn-1 assertion read turn-N
# state and pass against a lie.


async def test_recorded_messages_are_not_the_callers_list():
    fake = FakeLLM()
    fake.queue_text("ok")
    messages = [{"role": "user", "content": "hi"}]

    await fake.complete(model="intake-jd", messages=messages)
    messages.append({"role": "assistant", "content": "turn 2"})
    messages.append({"role": "user", "content": "turn 3"})

    assert fake.calls[0]["messages"] == [{"role": "user", "content": "hi"}]
    assert fake.calls[0]["messages"] is not messages


async def test_recorded_tools_are_not_the_callers_list():
    fake = FakeLLM()
    fake.queue_text("ok")
    tools = [{"type": "function", "function": {"name": "a"}}]

    await fake.complete(model="intake-jd", messages=[], tools=tools)
    tools.append({"type": "function", "function": {"name": "b"}})

    assert len(fake.calls[0]["tools"]) == 1
    assert fake.calls[0]["tools"] is not tools


async def test_an_agent_loop_records_each_turn_separately():
    """The exact multi-turn shape the five services use."""
    fake = FakeLLM()
    fake.queue_tool_call("emit_job_description", {"title": "SRE"})
    fake.queue_text("done")
    messages = [{"role": "user", "content": "write a JD"}]

    await fake.complete(model="intake-jd", messages=messages, tools=[])
    messages.append({"role": "assistant", "content": "calling tool"})
    messages.append({"role": "user", "content": "tool result"})
    await fake.complete(model="intake-jd", messages=messages, tools=[])

    assert len(fake.calls[0]["messages"]) == 1
    assert len(fake.calls[1]["messages"]) == 3
    assert fake.calls[0]["messages"] is not fake.calls[1]["messages"]


async def test_stream_turn_also_snapshots_its_messages():
    fake = FakeLLM()
    fake.queue_text("ok")
    messages = [{"role": "user", "content": "hi"}]

    [e async for e in fake.stream_turn(model="debrief-chat", messages=messages)]
    messages.append({"role": "assistant", "content": "later"})

    assert len(fake.calls[0]["messages"]) == 1


async def test_recorded_tools_stay_none_when_none_was_passed():
    """None and [] are different things to the real client; keep the distinction."""
    fake = FakeLLM()
    fake.queue_text("ok")

    await fake.complete(model="intake-jd", messages=[])

    assert fake.calls[0]["tools"] is None


# --- the reply carries the alias, never "fake" ----------------------------


async def test_reply_model_is_the_alias_the_caller_passed():
    """The real client stamps the reply with the alias it was called with. A
    reply left saying "fake" makes `reply.model` untestable for any consumer
    that logs or routes on it."""
    fake = FakeLLM()
    fake.queue_text("hello")

    reply = await fake.complete(model="intake-jd", messages=[])

    assert reply.model == "intake-jd"


async def test_tool_call_reply_also_carries_the_alias():
    fake = FakeLLM()
    fake.queue_tool_call("emit_job_description", {"title": "SRE"})

    reply = await fake.complete(model="debrief-chat", messages=[], tools=[])

    assert reply.model == "debrief-chat"


async def test_queue_reply_is_restamped_with_the_alias():
    fake = FakeLLM()
    fake.queue_reply(LLMReply(text="x", model="whatever-the-test-wrote", finish_reason="stop"))

    reply = await fake.complete(model="intake-jd", messages=[])

    assert reply.model == "intake-jd"


async def test_the_same_alias_reaches_both_the_reply_and_the_record():
    fake = FakeLLM()
    fake.queue_text("hello")

    reply = await fake.complete(model="intake-jd", messages=[])

    assert reply.model == fake.calls[0]["model"]


# --- multi-delta streaming ------------------------------------------------


async def test_queue_text_streams_more_than_one_delta():
    """The whole point: a consumer cannot assume a single text event, because
    the real client yields once per content chunk the provider sends."""
    fake = FakeLLM()
    fake.queue_text("one two three four")

    events = [e async for e in fake.stream_turn(model="debrief-chat", messages=[])]
    text_events = [payload for kind, payload in events if kind == "text"]

    assert len(text_events) > 1
    assert "".join(text_events) == "one two three four"


async def test_queue_text_deltas_streams_exactly_the_given_parts():
    fake = FakeLLM()
    fake.queue_text_deltas("Hel", "lo, ", "wor", "ld")

    events = [e async for e in fake.stream_turn(model="debrief-chat", messages=[])]

    assert [p for k, p in events if k == "text"] == ["Hel", "lo, ", "wor", "ld"]
    assert events[-1] == ("done", {"text": "Hello, world", "stop_reason": "stop"})


async def test_queue_text_deltas_reassembles_for_complete():
    """The same queued outcome must read as one whole reply through complete()."""
    fake = FakeLLM()
    fake.queue_text_deltas("Hel", "lo, ", "wor", "ld")

    reply = await fake.complete(model="intake-jd", messages=[])

    assert reply.text == "Hello, world"


async def test_deltas_concatenate_to_the_done_text_exactly():
    fake = FakeLLM()
    fake.queue_text("  leading and trailing  ")

    events = [e async for e in fake.stream_turn(model="debrief-chat", messages=[])]

    joined = "".join(p for k, p in events if k == "text")
    assert joined == "  leading and trailing  "
    assert events[-1][1]["text"] == joined


async def test_empty_delta_parts_are_not_emitted():
    """The real client yields only on a truthy content delta."""
    fake = FakeLLM()
    fake.queue_text_deltas("a", "", "b")

    events = [e async for e in fake.stream_turn(model="debrief-chat", messages=[])]

    assert [p for k, p in events if k == "text"] == ["a", "b"]


async def test_deltas_precede_tool_calls_which_precede_done():
    fake = FakeLLM()
    fake.queue_reply(
        LLMReply(
            text="thinking out loud",
            model="fake",
            tool_calls=[ToolCall(id="c1", name="emit_job_description", arguments={})],
            finish_reason="tool_calls",
        )
    )

    events = [e async for e in fake.stream_turn(model="intake-jd", messages=[])]
    kinds = [k for k, _ in events]

    assert kinds.count("done") == 1
    assert kinds[-1] == "done"
    assert kinds.index("tool_call") > max(i for i, k in enumerate(kinds) if k == "text")


# --- queued errors are the type production can actually raise -------------


async def test_a_plain_exception_is_coerced_to_llmerror():
    """Both real methods normalize every provider failure to LLMError, so a
    migrated test must not be able to write `except ValueError` around a call
    site that can only ever see LLMError."""
    fake = FakeLLM()
    fake.queue_error(ValueError("bad json"))

    with pytest.raises(LLMError, match="bad json"):
        await fake.complete(model="intake-jd", messages=[])


async def test_coercion_keeps_the_original_exception_as_the_cause():
    fake = FakeLLM()
    original = ValueError("bad json")
    fake.queue_error(original)

    with pytest.raises(LLMError) as caught:
        await fake.complete(model="intake-jd", messages=[])

    assert caught.value.__cause__ is original


async def test_a_queued_llmerror_passes_through_untouched():
    fake = FakeLLM()
    original = LLMError("gateway down", alias="intake-jd", status=503)
    fake.queue_error(original)

    with pytest.raises(LLMError) as caught:
        await fake.complete(model="intake-jd", messages=[])

    assert caught.value is original
    assert caught.value.status == 503


async def test_an_llmerror_subclass_is_not_flattened():
    fake = FakeLLM()
    fake.queue_error(ToolEmulationError("model returned prose"))

    with pytest.raises(ToolEmulationError):
        await fake.complete(model="intake-jd", messages=[])


async def test_cancellation_propagates_untouched():
    """CancelledError is a BaseException, not an Exception. The real client lets
    it through rather than normalizing it, and so must the fake — coercing it
    would make a cooperative-cancellation test impossible to write."""
    fake = FakeLLM()
    fake.queue_error(asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await fake.complete(model="intake-jd", messages=[])


async def test_keyboardinterrupt_propagates_untouched():
    fake = FakeLLM()
    fake.queue_error(KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        await fake.complete(model="intake-jd", messages=[])


async def test_a_messageless_exception_still_yields_a_readable_error():
    """errors.py exists because the Anthropic-era invoker logged 'Failed to
    trigger job: ' with an empty message."""
    fake = FakeLLM()
    fake.queue_error(ValueError())

    with pytest.raises(LLMError, match="ValueError"):
        await fake.complete(model="intake-jd", messages=[])


# --- tool shape is rejected here exactly as it is on the real client ----------
#
# The real client validates tool shape before dispatch, so an Anthropic-shaped
# spec never leaves the process. A fake that stored the same spec verbatim would
# let a migrating call site forget the translation and still pass its whole
# suite — the bug would surface only against the gateway, which is precisely the
# failure the guard was added to prevent, relocated into the test seam.


ANTHROPIC_TOOL = {
    "name": "emit_job_description",
    "description": "Return the structured job description.",
    "input_schema": {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    },
}

OPENAI_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_job_description",
        "description": "Return the structured job description.",
        "parameters": {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        },
    },
}


class _Caps:
    def __init__(self, supported=True):
        self.supported = supported
        self.asked = []

    async def supports_tools(self, alias):
        self.asked.append(alias)
        return self.supported


class _Stream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for chunk in self._chunks:
            yield chunk


class _Completions:
    """One gateway stand-in serving both entry points, so a single real client
    can be compared against the fake on complete() and stream_turn() alike."""

    def __init__(self):
        self.sent = []

    async def create(self, **kwargs):
        self.sent.append(kwargs)
        if kwargs.get("stream"):
            delta = SimpleNamespace(content="hello", tool_calls=None)
            return _Stream([SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason="stop")])])
        message = SimpleNamespace(content="hello", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


def _real_client():
    completions = _Completions()
    client = LLMClient(
        openai_client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        capabilities=_Caps(),
    )
    return client, completions


async def _error_from_complete(client, tools):
    try:
        await client.complete(
            model="intake-jd", messages=[{"role": "user", "content": "hi"}], tools=tools
        )
    except Exception as exc:  # noqa: BLE001 — the type is what the test asserts on
        return exc
    return None


async def _error_from_stream(client, tools):
    try:
        async for _ in client.stream_turn(
            model="intake-jd", messages=[{"role": "user", "content": "hi"}], tools=tools
        ):
            pass
    except Exception as exc:  # noqa: BLE001 — the type is what the test asserts on
        return exc
    return None


async def test_complete_rejects_an_anthropic_shaped_tool():
    fake = FakeLLM()
    fake.queue_text("must not be returned")

    with pytest.raises(ToolEmulationError) as caught:
        await fake.complete(
            model="intake-jd",
            messages=[{"role": "user", "content": "hi"}],
            tools=[ANTHROPIC_TOOL],
        )

    message = str(caught.value)
    assert "input_schema" in message
    assert "emit_job_description" in message
    assert fake.calls == [], "a rejected call must not be recorded"

    # The queued reply survived, which is how we know the guard ran before the
    # queue was consumed — same ordering as the real client, which dispatches
    # nothing when validation fails.
    reply = await fake.complete(model="intake-jd", messages=[], tools=[OPENAI_TOOL])
    assert reply.text == "must not be returned"


async def test_stream_turn_rejects_an_anthropic_shaped_tool():
    fake = FakeLLM()
    fake.queue_text("must not be returned")

    with pytest.raises(ToolEmulationError) as caught:
        async for _ in fake.stream_turn(
            model="debrief-chat",
            messages=[{"role": "user", "content": "hi"}],
            tools=[ANTHROPIC_TOOL],
        ):
            pass

    message = str(caught.value)
    assert "input_schema" in message
    assert "emit_job_description" in message
    assert fake.calls == [], "a rejected call must not be recorded"

    events = [
        event
        async for event in fake.stream_turn(model="debrief-chat", messages=[], tools=[OPENAI_TOOL])
    ]
    assert ("done", {"text": "must not be returned", "stop_reason": "stop"}) in events


async def test_complete_still_accepts_an_openai_shaped_tool():
    """The guard must reject malformed specs only, not narrow what tools mean."""
    fake = FakeLLM()
    fake.queue_tool_call("emit_job_description", {"title": "SRE"})

    reply = await fake.complete(model="intake-jd", messages=[], tools=[OPENAI_TOOL])

    assert reply.tool_call_named("emit_job_description").arguments == {"title": "SRE"}
    assert fake.calls[0]["tools"] == [OPENAI_TOOL]


async def test_stream_turn_still_accepts_an_openai_shaped_tool():
    fake = FakeLLM()
    fake.queue_tool_call("emit_job_description", {"title": "SRE"})

    events = [
        event
        async for event in fake.stream_turn(model="debrief-chat", messages=[], tools=[OPENAI_TOOL])
    ]

    assert (
        "tool_call",
        {"id": "fake-emit_job_description", "name": "emit_job_description", "input": {"title": "SRE"}},
    ) in events
    assert fake.calls[0]["tools"] == [OPENAI_TOOL]


async def test_a_tool_spec_that_is_not_a_dict_is_rejected_too():
    fake = FakeLLM()
    fake.queue_text("must not be returned")

    with pytest.raises(ToolEmulationError):
        await fake.complete(model="intake-jd", messages=[], tools=["emit_job_description"])

    assert fake.calls == []


async def test_the_fake_and_the_real_client_reject_an_anthropic_tool_identically():
    """The anti-drift test.

    Two implementations of the same guard would pass every test above and still
    diverge later. Both must reach the same `validate_tool_shape`, so both must
    raise the same type with the same wording, from both entry points.
    """
    fake = FakeLLM()
    real, gateway = _real_client()

    for entry in (_error_from_complete, _error_from_stream):
        fake_error = await entry(fake, [ANTHROPIC_TOOL])
        real_error = await entry(real, [ANTHROPIC_TOOL])

        assert type(fake_error) is ToolEmulationError, f"{entry.__name__}: {fake_error!r}"
        assert type(real_error) is type(fake_error), (
            f"{entry.__name__}: real client raised {real_error!r}, fake raised {fake_error!r}"
        )
        assert str(real_error) == str(fake_error)

    assert gateway.sent == [], "a malformed tool spec must never reach the gateway"
    assert fake.calls == []


@pytest.mark.parametrize("tools", [None, []])
async def test_a_falsy_tool_list_is_validated_by_neither(tools):
    """Both guards sit behind `if tools:`. None and [] must stay non-events —
    `tools=[]` in particular is already how a dozen tests call the fake."""
    fake = FakeLLM()
    fake.queue_text("ok")
    fake.queue_text("ok")
    real, _ = _real_client()

    assert await _error_from_complete(fake, tools) is None
    assert await _error_from_complete(real, tools) is None
    assert await _error_from_stream(fake, tools) is None
    assert await _error_from_stream(real, tools) is None
