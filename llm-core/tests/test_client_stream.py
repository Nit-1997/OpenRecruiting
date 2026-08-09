import asyncio
import json
import typing
from types import SimpleNamespace

import pytest
import structlog

from llm_core.client import LLMClient
from llm_core.errors import LLMError, ToolEmulationError


class FakeCaps:
    def __init__(self, supported=True):
        self.supported = supported

    async def supports_tools(self, alias):
        return self.supported


def _chunk(content=None, tool=None, finish=None):
    delta = SimpleNamespace(content=content, tool_calls=tool)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish)])


def _tool_delta(index, call_id=None, name=None, args=None):
    return [
        SimpleNamespace(
            index=index,
            id=call_id,
            function=SimpleNamespace(name=name, arguments=args),
        )
    ]


class FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for c in self._chunks:
            yield c


def _openai_stub(chunks, recorder):
    class Completions:
        async def create(self, **kwargs):
            recorder.append(kwargs)
            return FakeStream(chunks)

    return SimpleNamespace(chat=SimpleNamespace(completions=Completions()))


async def _collect(iterator):
    return [event async for event in iterator]


async def test_streams_text_then_done():
    sent = []
    client = LLMClient(
        openai_client=_openai_stub([_chunk(content="Hel"), _chunk(content="lo"), _chunk(finish="stop")], sent),
        capabilities=FakeCaps(),
    )

    events = await _collect(
        client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
    )

    assert ("text", "Hel") in events
    assert ("text", "lo") in events
    kind, payload = events[-1]
    assert kind == "done"
    assert payload["text"] == "Hello"
    assert payload["stop_reason"] == "stop"


async def test_assembles_tool_call_across_chunks():
    sent = []
    chunks = [
        _chunk(tool=_tool_delta(0, call_id="call_1", name="update_answer", args='{"qid"')),
        _chunk(tool=_tool_delta(0, args=': "q4_must_haves"}')),
        _chunk(finish="tool_calls"),
    ]
    client = LLMClient(openai_client=_openai_stub(chunks, sent), capabilities=FakeCaps())

    events = await _collect(
        client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
    )

    tool_events = [e for e in events if e[0] == "tool_call"]
    assert len(tool_events) == 1
    assert tool_events[0][1] == {
        "id": "call_1",
        "name": "update_answer",
        "input": {"qid": "q4_must_haves"},
    }


async def test_malformed_tool_json_yields_empty_input_not_a_crash():
    sent = []
    chunks = [
        _chunk(tool=_tool_delta(0, call_id="call_1", name="update_answer", args="{not json")),
        _chunk(finish="tool_calls"),
    ]
    client = LLMClient(openai_client=_openai_stub(chunks, sent), capabilities=FakeCaps())

    events = await _collect(
        client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
    )

    tool_events = [e for e in events if e[0] == "tool_call"]
    assert tool_events[0][1]["input"] == {}


async def test_stream_flag_and_system_message_are_sent():
    sent = []
    client = LLMClient(openai_client=_openai_stub([_chunk(finish="stop")], sent), capabilities=FakeCaps())

    await _collect(
        client.stream_turn(
            model="debrief-chat", system="be terse", messages=[{"role": "user", "content": "hi"}]
        )
    )

    assert sent[0]["stream"] is True
    assert sent[0]["messages"][0] == {"role": "system", "content": "be terse"}


# --- Nothing but LLMError may escape, and it must escape ON ITERATION ---------
#
# stream_turn is an async generator: its body does not run until the caller
# iterates. A provider blowing up therefore surfaces inside the consumer's
# `async for`, which is the only place `except LLMError` can catch it.

TOOL = {
    "type": "function",
    "function": {
        "name": "update_answer",
        "description": "Record an answer.",
        "parameters": {
            "type": "object",
            "properties": {"qid": {"type": "string"}},
            "required": ["qid"],
        },
    },
}


class RecordingCaps(FakeCaps):
    def __init__(self, supported=True):
        super().__init__(supported)
        self.asked = []

    async def supports_tools(self, alias):
        self.asked.append(alias)
        return await super().supports_tools(alias)


class ExplodingStream:
    """Yields the given chunks, then raises — a connection dropped mid-response."""

    def __init__(self, chunks, error):
        self._chunks = chunks
        self._error = error

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for c in self._chunks:
            yield c
        raise self._error


class ClosableStream(FakeStream):
    def __init__(self, chunks, close_error=None):
        super().__init__(chunks)
        self.closed = 0
        self._close_error = close_error

    async def close(self):
        self.closed += 1
        if self._close_error is not None:
            raise self._close_error


def _stub_returning(stream, recorder):
    class Completions:
        async def create(self, **kwargs):
            recorder.append(kwargs)
            if isinstance(stream, BaseException):
                raise stream
            return stream

    return SimpleNamespace(chat=SimpleNamespace(completions=Completions()))


async def test_transport_failure_surfaces_as_llmerror_only_on_iteration():
    sent = []
    client = LLMClient(
        openai_client=_stub_returning(RuntimeError("gateway refused"), sent),
        capabilities=FakeCaps(),
    )

    # Constructing the generator must not raise — nothing has run yet.
    stream = client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
    assert sent == []

    with pytest.raises(LLMError) as exc:
        await _collect(stream)

    assert "debrief-chat" in str(exc.value)
    assert "gateway refused" in str(exc.value)


async def test_transport_status_error_carries_status_through():
    sent = []
    boom = RuntimeError("gateway said no")
    boom.status_code = 503
    client = LLMClient(openai_client=_stub_returning(boom, sent), capabilities=FakeCaps())

    with pytest.raises(LLMError) as exc:
        await _collect(
            client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
        )

    assert exc.value.status == 503


async def test_midstream_failure_surfaces_as_llmerror_not_the_raw_exception():
    """The connection dies after some prose has already been delivered. The caller
    is mid-`async for`; a raw provider exception there sails past `except LLMError`."""
    sent = []
    stream = ExplodingStream(
        [_chunk(content="Hel")], ConnectionResetError("peer closed the connection")
    )
    client = LLMClient(openai_client=_stub_returning(stream, sent), capabilities=FakeCaps())

    seen = []
    with pytest.raises(LLMError) as exc:
        async for event in client.stream_turn(
            model="debrief-chat", messages=[{"role": "user", "content": "hi"}]
        ):
            seen.append(event)

    assert seen == [("text", "Hel")]
    assert "debrief-chat" in str(exc.value)
    assert "peer closed the connection" in str(exc.value)


async def test_midstream_cancellation_is_never_swallowed():
    """CancelledError is a BaseException and must unwind the caller, not arrive as
    a bogus LLMError describing a provider failure that never happened."""
    sent = []
    stream = ExplodingStream([_chunk(content="Hel")], asyncio.CancelledError())
    client = LLMClient(openai_client=_stub_returning(stream, sent), capabilities=FakeCaps())

    with pytest.raises(asyncio.CancelledError):
        await _collect(
            client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
        )


async def test_non_subscriptable_choices_raises_llmerror():
    sent = []
    # Truthy, so a `not chunk.choices` guard passes, but choices[0] is a TypeError.
    bad = SimpleNamespace(choices=SimpleNamespace())
    client = LLMClient(openai_client=_stub_returning(FakeStream([bad]), sent), capabilities=FakeCaps())

    with pytest.raises(LLMError) as exc:
        await _collect(
            client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
        )

    assert "debrief-chat" in str(exc.value)


async def test_non_string_content_raises_llmerror():
    """A list-shaped content delta would otherwise reach "".join() and throw a raw
    TypeError from the final event, outside any normalization."""
    sent = []
    chunks = [_chunk(content=[{"type": "text", "text": "hi"}]), _chunk(finish="stop")]
    client = LLMClient(openai_client=_stub_returning(FakeStream(chunks), sent), capabilities=FakeCaps())

    with pytest.raises(LLMError):
        await _collect(
            client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
        )


async def test_chunk_without_choices_is_skipped_not_fatal():
    """Gateways interleave keepalive/usage frames carrying no choices."""
    sent = []
    chunks = [SimpleNamespace(), _chunk(content="hi"), SimpleNamespace(choices=[]), _chunk(finish="stop")]
    client = LLMClient(openai_client=_stub_returning(FakeStream(chunks), sent), capabilities=FakeCaps())

    events = await _collect(
        client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
    )

    assert ("text", "hi") in events
    assert events[-1][1]["stop_reason"] == "stop"


async def test_missing_finish_reason_leaves_stop_reason_none():
    sent = []
    chunk_without_finish = SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content="hi", tool_calls=None))]
    )
    client = LLMClient(
        openai_client=_stub_returning(FakeStream([chunk_without_finish]), sent), capabilities=FakeCaps()
    )

    events = await _collect(
        client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
    )

    assert events[-1] == ("done", {"text": "hi", "stop_reason": None})


# --- Tool assembly -----------------------------------------------------------


async def test_two_tool_calls_with_interleaved_deltas_are_emitted_separately():
    sent = []
    chunks = [
        _chunk(tool=_tool_delta(0, call_id="call_a", name="update_answer", args='{"qid": ')),
        _chunk(tool=_tool_delta(1, call_id="call_b", name="mark_status", args='{"done"')),
        _chunk(tool=_tool_delta(0, args='"q1"}')),
        _chunk(tool=_tool_delta(1, args=": true}")),
        _chunk(finish="tool_calls"),
    ]
    client = LLMClient(openai_client=_stub_returning(FakeStream(chunks), sent), capabilities=FakeCaps())

    events = await _collect(
        client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
    )

    calls = [payload for kind, payload in events if kind == "tool_call"]
    assert calls == [
        {"id": "call_a", "name": "update_answer", "input": {"qid": "q1"}},
        {"id": "call_b", "name": "mark_status", "input": {"done": True}},
    ]
    # Every tool call lands before 'done', and prose-free turns report empty text.
    assert events[-1] == ("done", {"text": "", "stop_reason": "tool_calls"})


async def test_tool_delta_without_an_index_still_assembles():
    """Not every gateway echoes `index` on a single tool call. Reading it as an
    attribute unconditionally would turn that into a dead turn."""
    sent = []
    indexless = [SimpleNamespace(id="call_1", function=SimpleNamespace(name="update_answer", arguments='{"qid": "q1"}'))]
    chunks = [_chunk(tool=indexless), _chunk(finish="tool_calls")]
    client = LLMClient(openai_client=_stub_returning(FakeStream(chunks), sent), capabilities=FakeCaps())

    events = await _collect(
        client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
    )

    calls = [payload for kind, payload in events if kind == "tool_call"]
    assert calls == [{"id": "call_1", "name": "update_answer", "input": {"qid": "q1"}}]


async def test_malformed_tool_json_is_never_logged_verbatim():
    """The argument buffer is model output: in this product it carries candidate
    names and hiring signals, so only its shape may reach a log line."""
    sent = []
    leaky = '{"candidate_name": "Ada Lovelace", "feedback": "strong hire, ship it"'
    chunks = [
        _chunk(tool=_tool_delta(0, call_id="call_1", name="update_answer", args=leaky)),
        _chunk(finish="tool_calls"),
    ]
    client = LLMClient(openai_client=_stub_returning(FakeStream(chunks), sent), capabilities=FakeCaps())

    with structlog.testing.capture_logs() as logs:
        events = await _collect(
            client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
        )

    rendered = json.dumps(logs)
    assert logs, "the malformed buffer should still be reported"
    assert "Ada Lovelace" not in rendered
    assert "strong hire" not in rendered
    assert "candidate_name" not in rendered
    assert [p for k, p in events if k == "tool_call"][0]["input"] == {}


async def test_already_decoded_tool_arguments_are_used_not_concatenated():
    """Some gateways hand `arguments` back already decoded. `buf += dict` is a
    TypeError, which would kill the turn over a payload that arrived intact."""
    sent = []
    decoded = [SimpleNamespace(index=0, id="call_1", function=SimpleNamespace(name="update_answer", arguments={"qid": "q1"}))]
    chunks = [_chunk(tool=decoded), _chunk(finish="tool_calls")]
    client = LLMClient(openai_client=_stub_returning(FakeStream(chunks), sent), capabilities=FakeCaps())

    events = await _collect(
        client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
    )

    assert [p for k, p in events if k == "tool_call"][0]["input"] == {"qid": "q1"}


async def test_non_object_tool_arguments_degrade_to_empty_input_without_logging_them():
    """`input` is contractually a dict — consumers index into it. A JSON array that
    parses cleanly must not be handed through as one."""
    sent = []
    chunks = [
        _chunk(tool=_tool_delta(0, call_id="call_1", name="update_answer", args='["Ada Lovelace"]')),
        _chunk(finish="tool_calls"),
    ]
    client = LLMClient(openai_client=_stub_returning(FakeStream(chunks), sent), capabilities=FakeCaps())

    with structlog.testing.capture_logs() as logs:
        events = await _collect(
            client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
        )

    assert [p for k, p in events if k == "tool_call"][0]["input"] == {}
    assert logs
    assert "Ada Lovelace" not in json.dumps(logs)


async def test_nameless_tool_call_carrying_arguments_raises_llmerror():
    """complete() rejects a tool call with no function name; streaming must too.

    text_runner indexes tc["id"] and tc["name"] straight into an Anthropic
    tool_use block, so emitting {"id": None, "name": None} buys a 400 on the very
    next turn — one turn away from the delta that actually caused it.
    """
    sent = []
    nameless = [SimpleNamespace(index=0, id=None, function=SimpleNamespace(name=None, arguments='{"qid": "q1"}'))]
    chunks = [_chunk(tool=nameless), _chunk(finish="tool_calls")]
    client = LLMClient(openai_client=_stub_returning(FakeStream(chunks), sent), capabilities=FakeCaps())

    with pytest.raises(LLMError) as exc:
        await _collect(
            client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
        )

    assert "debrief-chat" in str(exc.value)
    assert "name" in str(exc.value)


async def test_nameless_tool_call_error_never_quotes_the_arguments():
    sent = []
    leaky = '{"candidate_name": "Ada Lovelace"}'
    nameless = [SimpleNamespace(index=0, id=None, function=SimpleNamespace(name=None, arguments=leaky))]
    chunks = [_chunk(tool=nameless), _chunk(finish="tool_calls")]
    client = LLMClient(openai_client=_stub_returning(FakeStream(chunks), sent), capabilities=FakeCaps())

    with structlog.testing.capture_logs() as logs:
        with pytest.raises(LLMError) as exc:
            await _collect(
                client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
            )

    assert "Ada Lovelace" not in str(exc.value)
    assert "Ada Lovelace" not in json.dumps(logs)


async def test_bare_sentinel_delta_never_manufactures_a_phantom_tool_call():
    """A delta that is nothing but {"index": 0} opens a slot and fills nothing.
    Emitting it invents a call the model never made."""
    sent = []
    chunks = [_chunk(tool=[SimpleNamespace(index=0)]), _chunk(content="thinking"), _chunk(finish="stop")]
    client = LLMClient(openai_client=_stub_returning(FakeStream(chunks), sent), capabilities=FakeCaps())

    events = await _collect(
        client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
    )

    assert [e for e in events if e[0] == "tool_call"] == []
    assert events[-1] == ("done", {"text": "thinking", "stop_reason": "stop"})


async def test_a_sentinel_delta_does_not_suppress_a_real_call_beside_it():
    sent = []
    chunks = [
        _chunk(tool=_tool_delta(0, call_id="call_a", name="update_answer", args='{"qid": "q1"}')),
        _chunk(tool=[SimpleNamespace(index=1)]),
        _chunk(finish="tool_calls"),
    ]
    client = LLMClient(openai_client=_stub_returning(FakeStream(chunks), sent), capabilities=FakeCaps())

    events = await _collect(
        client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
    )

    assert [p for k, p in events if k == "tool_call"] == [
        {"id": "call_a", "name": "update_answer", "input": {"qid": "q1"}}
    ]


async def test_a_named_tool_call_with_no_arguments_still_emits():
    """A tool that takes no parameters is legitimate — an empty input is not a phantom."""
    sent = []
    chunks = [_chunk(tool=_tool_delta(0, call_id="call_1", name="mark_status")), _chunk(finish="tool_calls")]
    client = LLMClient(openai_client=_stub_returning(FakeStream(chunks), sent), capabilities=FakeCaps())

    events = await _collect(
        client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
    )

    assert [p for k, p in events if k == "tool_call"] == [
        {"id": "call_1", "name": "mark_status", "input": {}}
    ]


# --- Tool routing ------------------------------------------------------------


async def test_native_tools_are_forwarded_when_the_model_supports_them():
    sent = []
    caps = RecordingCaps(supported=True)
    client = LLMClient(openai_client=_stub_returning(FakeStream([_chunk(finish="stop")]), sent), capabilities=caps)

    await _collect(
        client.stream_turn(
            model="debrief-chat", messages=[{"role": "user", "content": "hi"}], tools=[TOOL]
        )
    )

    assert sent[0]["tools"] == [TOOL]
    assert caps.asked == ["debrief-chat"]


async def test_emulation_instruction_is_prepended_below_the_system_message():
    sent = []
    caps = RecordingCaps(supported=False)
    client = LLMClient(openai_client=_stub_returning(FakeStream([_chunk(finish="stop")]), sent), capabilities=caps)

    await _collect(
        client.stream_turn(
            model="debrief-local",
            system="be terse",
            messages=[{"role": "user", "content": "hi"}],
            tools=[TOOL],
        )
    )

    messages = sent[0]["messages"]
    assert "tools" not in sent[0]
    assert messages[0] == {"role": "system", "content": "be terse"}
    assert "update_answer" in messages[1]["content"]
    assert messages[2] == {"role": "user", "content": "hi"}


async def test_degrading_to_emulated_tools_is_logged():
    """Streaming plus emulated tools yields the JSON as prose and never a
    tool_call. A caller expecting one gets nothing, so the degradation has to be
    visible in production rather than only in the docstring."""
    sent = []
    caps = RecordingCaps(supported=False)
    client = LLMClient(openai_client=_stub_returning(FakeStream([_chunk(finish="stop")]), sent), capabilities=caps)

    with structlog.testing.capture_logs() as logs:
        await _collect(
            client.stream_turn(
                model="debrief-local", messages=[{"role": "user", "content": "hi"}], tools=[TOOL]
            )
        )

    degraded = [entry for entry in logs if entry["event"] == "llm_stream_tools_emulated"]
    assert len(degraded) == 1
    assert degraded[0]["alias"] == "debrief-local"
    assert degraded[0]["tools"] == 1
    assert degraded[0]["log_level"] == "warning"


async def test_native_tool_support_logs_no_degradation_warning():
    sent = []
    caps = RecordingCaps(supported=True)
    client = LLMClient(openai_client=_stub_returning(FakeStream([_chunk(finish="stop")]), sent), capabilities=caps)

    with structlog.testing.capture_logs() as logs:
        await _collect(
            client.stream_turn(
                model="debrief-chat", messages=[{"role": "user", "content": "hi"}], tools=[TOOL]
            )
        )

    assert [entry for entry in logs if entry["event"] == "llm_stream_tools_emulated"] == []


async def test_empty_tool_list_is_treated_as_no_tools():
    """build_emulation_instruction raises on an empty list, so it must not be reached."""
    sent = []
    caps = RecordingCaps(supported=False)
    client = LLMClient(openai_client=_stub_returning(FakeStream([_chunk(finish="stop")]), sent), capabilities=caps)

    events = await _collect(
        client.stream_turn(
            model="debrief-chat", messages=[{"role": "user", "content": "hi"}], tools=[]
        )
    )

    assert events[-1][0] == "done"
    assert caps.asked == []
    assert "tools" not in sent[0]
    assert sent[0]["messages"] == [{"role": "user", "content": "hi"}]


# --- Resource hygiene --------------------------------------------------------


async def test_abandoning_the_stream_early_closes_the_provider_response():
    """An SSE client that disconnects mid-answer leaves the upstream HTTP response
    open until GC unless the generator releases it on the way out."""
    sent = []
    stream = ClosableStream([_chunk(content="Hel"), _chunk(content="lo"), _chunk(finish="stop")])
    client = LLMClient(openai_client=_stub_returning(stream, sent), capabilities=FakeCaps())

    events = client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
    async for _ in events:
        break
    await events.aclose()

    assert stream.closed == 1


async def test_a_failing_close_never_reaches_the_caller():
    sent = []
    stream = ClosableStream([_chunk(finish="stop")], close_error=RuntimeError("socket already gone"))
    client = LLMClient(openai_client=_stub_returning(stream, sent), capabilities=FakeCaps())

    events = await _collect(
        client.stream_turn(model="debrief-chat", messages=[{"role": "user", "content": "hi"}])
    )

    assert events[-1][0] == "done"
    assert stream.closed == 1


# --- Annotations -------------------------------------------------------------


def test_stream_turn_annotations_resolve():
    """client.py uses `from __future__ import annotations`, so a missing typing
    import is invisible at runtime and only shows up here or in a type checker."""
    hints = typing.get_type_hints(LLMClient.stream_turn)

    assert hints["return"] is not None
    assert hints["max_tokens"] is int


# --- Tool shape is validated on both dispatch paths --------------------------

STREAM_TOOL = {
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

ANTHROPIC_TOOL = {
    "name": "emit_job_description",
    "description": "Return the structured job description.",
    "input_schema": {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    },
}


class RecordingCaps:
    def __init__(self, supported=True):
        self.supported = supported
        self.asked = []

    async def supports_tools(self, alias):
        self.asked.append(alias)
        return self.supported


async def test_stream_rejects_an_anthropic_shaped_tool_on_the_native_path():
    """stream_turn used to forward payload["tools"] unvalidated on a capable alias."""
    sent = []
    caps = RecordingCaps(supported=True)
    client = LLMClient(openai_client=_openai_stub([_chunk(finish="stop")], sent), capabilities=caps)

    with pytest.raises(ToolEmulationError) as exc:
        await _collect(
            client.stream_turn(
                model="debrief-chat",
                messages=[{"role": "user", "content": "hi"}],
                tools=[ANTHROPIC_TOOL],
            )
        )

    message = str(exc.value)
    assert "input_schema" in message
    assert "emit_job_description" in message
    assert sent == [], "a malformed tool spec must never reach the gateway"
    assert caps.asked == [], "shape must be checked before the capability probe"


async def test_stream_rejects_an_anthropic_shaped_tool_on_the_emulated_path():
    sent = []
    client = LLMClient(
        openai_client=_openai_stub([_chunk(finish="stop")], sent),
        capabilities=RecordingCaps(supported=False),
    )

    with pytest.raises(ToolEmulationError) as exc:
        await _collect(
            client.stream_turn(
                model="debrief-chat",
                messages=[{"role": "user", "content": "hi"}],
                tools=[ANTHROPIC_TOOL],
            )
        )

    assert "input_schema" in str(exc.value)
    assert sent == []


async def test_stream_and_complete_reject_an_anthropic_tool_with_the_same_message():
    """One error, one wording, whichever entry point a migrating call site uses."""
    stream_client = LLMClient(
        openai_client=_openai_stub([_chunk(finish="stop")], []), capabilities=RecordingCaps()
    )
    with pytest.raises(ToolEmulationError) as stream_exc:
        await _collect(
            stream_client.stream_turn(
                model="debrief-chat",
                messages=[{"role": "user", "content": "hi"}],
                tools=[ANTHROPIC_TOOL],
            )
        )

    complete_stub = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kw: None)
        )
    )
    complete_client = LLMClient(openai_client=complete_stub, capabilities=RecordingCaps())
    with pytest.raises(ToolEmulationError) as complete_exc:
        await complete_client.complete(
            model="debrief-chat",
            messages=[{"role": "user", "content": "hi"}],
            tools=[ANTHROPIC_TOOL],
        )

    assert str(stream_exc.value) == str(complete_exc.value)


async def test_stream_still_forwards_a_well_shaped_tool():
    sent = []
    client = LLMClient(
        openai_client=_openai_stub([_chunk(finish="stop")], sent), capabilities=RecordingCaps()
    )

    await _collect(
        client.stream_turn(
            model="debrief-chat",
            messages=[{"role": "user", "content": "hi"}],
            tools=[STREAM_TOOL],
        )
    )

    assert sent[0]["tools"] == [STREAM_TOOL]
