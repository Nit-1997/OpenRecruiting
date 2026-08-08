"""FakeLLM is the testing contract for the whole migration.

Twenty-six test files across five services stop hand-building Anthropic response
objects and start queueing outcomes here. Every one of them is only as honest as
this double: a fake whose signatures or event shapes have drifted from the real
client lets a migrated test pass against something production can never produce.
The signature-parity tests below exist to make that drift fail loudly.
"""

import inspect

import pytest

from llm_core.client import LLMClient
from llm_core.errors import LLMError
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
    fake = FakeLLM()
    fake.queue_text("hi there")

    events = [e async for e in fake.stream_turn(model="debrief-chat", messages=[])]

    assert ("text", "hi there") in events
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


@pytest.mark.parametrize("method", ["complete", "stream_turn"])
def test_fake_signature_matches_the_real_client(method):
    real = inspect.signature(getattr(LLMClient, method))
    fake = inspect.signature(getattr(FakeLLM, method))

    assert fake == real, (
        f"FakeLLM.{method} has drifted from LLMClient.{method}.\n"
        f"  real: {real}\n"
        f"  fake: {fake}\n"
        "Migrated tests call the fake with the real client's keywords; a "
        "mismatch means they are testing a call production cannot make."
    )


def test_fake_covers_every_public_method_of_the_real_client():
    """Catches a method ADDED to LLMClient that the fake never grew.

    Signature parity only compares methods the fake already has, so a new
    `LLMClient.embed()` would sail past it and only fail once a service tried to
    substitute the fake for the client.
    """
    public = {
        name
        for name, _ in inspect.getmembers(LLMClient, inspect.isfunction)
        if not name.startswith("_")
    }

    missing = public - set(dir(FakeLLM))

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
