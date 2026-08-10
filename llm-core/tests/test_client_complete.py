import asyncio
import json
from types import SimpleNamespace

import httpx
import openai
import pytest
import structlog

from llm_core.client import LLMClient
from llm_core.errors import LLMError, ToolEmulationError

TOOL = {
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


class FakeCaps:
    def __init__(self, supported: bool = True):
        self.supported = supported
        self.asked = []

    async def supports_tools(self, alias):
        self.asked.append(alias)
        return self.supported


class FakeCompletions:
    def __init__(self, response, recorder):
        self._response = response
        self._recorder = recorder

    async def create(self, **kwargs):
        self._recorder.append(kwargs)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _openai_stub(response, recorder):
    return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions(response, recorder)))


def _text_response(text, finish="stop"):
    message = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish)], model="x"
    )


def _tool_response(name, args: dict):
    call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )
    message = SimpleNamespace(content=None, tool_calls=[call])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="tool_calls")], model="x"
    )


async def test_returns_plain_text():
    sent = []
    client = LLMClient(openai_client=_openai_stub(_text_response("hello"), sent), capabilities=FakeCaps())

    reply = await client.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}])

    assert reply.text == "hello"
    assert reply.tool_calls == []
    assert reply.emulated_tools is False


async def test_system_argument_becomes_a_system_message():
    sent = []
    client = LLMClient(openai_client=_openai_stub(_text_response("ok"), sent), capabilities=FakeCaps())

    await client.complete(
        model="intake-jd", system="be terse", messages=[{"role": "user", "content": "hi"}]
    )

    assert sent[0]["messages"][0] == {"role": "system", "content": "be terse"}
    assert sent[0]["messages"][1] == {"role": "user", "content": "hi"}


async def test_native_tool_call_is_normalized():
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_tool_response("emit_job_description", {"title": "SRE"}), sent),
        capabilities=FakeCaps(supported=True),
    )

    reply = await client.complete(
        model="intake-jd", messages=[{"role": "user", "content": "hi"}], tools=[TOOL]
    )

    assert reply.emulated_tools is False
    call = reply.tool_call_named("emit_job_description")
    assert call is not None
    assert call.arguments == {"title": "SRE"}
    assert sent[0]["tools"] == [TOOL]


async def test_falls_back_to_emulation_when_model_lacks_tools():
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_text_response('{"title": "SRE"}'), sent),
        capabilities=FakeCaps(supported=False),
    )

    reply = await client.complete(
        model="intake-jd-local", messages=[{"role": "user", "content": "hi"}], tools=[TOOL]
    )

    assert reply.emulated_tools is True
    assert reply.tool_call_named("emit_job_description").arguments == {"title": "SRE"}
    # The real tools param must NOT be sent to a model that cannot handle it.
    assert "tools" not in sent[0]
    assert sent[0]["response_format"] == {"type": "json_object"}
    assert "emit_job_description" in sent[0]["messages"][0]["content"]


async def test_upstream_failure_raises_llmerror_with_alias():
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(RuntimeError("upstream exploded"), sent),
        capabilities=FakeCaps(),
    )

    with pytest.raises(LLMError) as exc:
        await client.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}])

    assert "intake-jd" in str(exc.value)
    assert "upstream exploded" in str(exc.value)


async def test_empty_upstream_message_still_produces_readable_error():
    sent = []
    client = LLMClient(openai_client=_openai_stub(RuntimeError(""), sent), capabilities=FakeCaps())

    with pytest.raises(LLMError) as exc:
        await client.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}])

    assert str(exc.value).strip() != ""
    assert "unknown LLM failure" in str(exc.value)


# --- Provider failures must never escape as anything but LLMError -------------
#
# Call sites catch LLMError. An IndexError or AttributeError from an unexpected
# gateway body would sail straight past them, so every malformed shape below has
# to arrive as an LLMError naming the alias.


def _raw_response(**fields):
    return SimpleNamespace(**fields)


async def test_openai_sdk_connection_error_is_normalized():
    sent = []
    boom = openai.APIConnectionError(request=httpx.Request("POST", "http://gw/v1/x"))
    client = LLMClient(openai_client=_openai_stub(boom, sent), capabilities=FakeCaps())

    with pytest.raises(LLMError) as exc:
        await client.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}])

    assert "intake-jd" in str(exc.value)
    assert exc.value.alias == "intake-jd"


async def test_openai_status_error_carries_status_through():
    sent = []
    response = httpx.Response(503, request=httpx.Request("POST", "http://gw/v1/x"))
    boom = openai.APIStatusError("gateway said no", response=response, body=None)
    client = LLMClient(openai_client=_openai_stub(boom, sent), capabilities=FakeCaps())

    with pytest.raises(LLMError) as exc:
        await client.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}])

    assert exc.value.status == 503
    assert "status=503" in str(exc.value)


async def test_empty_choices_raises_llmerror_not_indexerror():
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_raw_response(choices=[], model="x"), sent),
        capabilities=FakeCaps(),
    )

    with pytest.raises(LLMError) as exc:
        await client.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}])

    assert "intake-jd" in str(exc.value)


async def test_response_without_choices_attribute_raises_llmerror():
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_raw_response(error="quota exceeded"), sent),
        capabilities=FakeCaps(),
    )

    with pytest.raises(LLMError):
        await client.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}])


async def test_choice_without_message_raises_llmerror():
    sent = []
    bad = _raw_response(choices=[SimpleNamespace(finish_reason="stop")], model="x")
    client = LLMClient(openai_client=_openai_stub(bad, sent), capabilities=FakeCaps())

    with pytest.raises(LLMError):
        await client.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}])


async def test_non_string_content_raises_llmerror():
    sent = []
    bad = _text_response([{"type": "text", "text": "hi"}])
    client = LLMClient(openai_client=_openai_stub(bad, sent), capabilities=FakeCaps())

    with pytest.raises(LLMError):
        await client.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}])


async def test_non_string_content_raises_llmerror_on_the_emulated_path():
    sent = []
    bad = _text_response([{"type": "text", "text": '{"title": "SRE"}'}])
    client = LLMClient(openai_client=_openai_stub(bad, sent), capabilities=FakeCaps(supported=False))

    with pytest.raises(LLMError):
        await client.complete(
            model="intake-jd-local", messages=[{"role": "user", "content": "hi"}], tools=[TOOL]
        )


async def test_malformed_tool_call_entry_raises_llmerror():
    sent = []
    message = SimpleNamespace(content=None, tool_calls=[SimpleNamespace(id="call_1")])
    bad = _raw_response(
        choices=[SimpleNamespace(message=message, finish_reason="tool_calls")], model="x"
    )
    client = LLMClient(openai_client=_openai_stub(bad, sent), capabilities=FakeCaps())

    with pytest.raises(LLMError):
        await client.complete(
            model="intake-jd", messages=[{"role": "user", "content": "hi"}], tools=[TOOL]
        )


async def test_unparsable_tool_arguments_degrade_to_empty_dict():
    sent = []
    call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="emit_job_description", arguments="{not json"),
    )
    message = SimpleNamespace(content=None, tool_calls=[call])
    bad = _raw_response(
        choices=[SimpleNamespace(message=message, finish_reason="tool_calls")], model="x"
    )
    client = LLMClient(openai_client=_openai_stub(bad, sent), capabilities=FakeCaps())

    reply = await client.complete(
        model="intake-jd", messages=[{"role": "user", "content": "hi"}], tools=[TOOL]
    )

    assert reply.tool_call_named("emit_job_description").arguments == {}


async def test_choice_without_finish_reason_still_returns_a_reply():
    sent = []
    message = SimpleNamespace(content="hello", tool_calls=None)
    bad = _raw_response(choices=[SimpleNamespace(message=message)], model="x")
    client = LLMClient(openai_client=_openai_stub(bad, sent), capabilities=FakeCaps())

    reply = await client.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}])

    assert reply.text == "hello"
    assert reply.finish_reason is None


async def test_emulation_parse_failure_surfaces_as_llmerror():
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_text_response("I am not JSON at all"), sent),
        capabilities=FakeCaps(supported=False),
    )

    with pytest.raises(LLMError):
        await client.complete(
            model="intake-jd-local", messages=[{"role": "user", "content": "hi"}], tools=[TOOL]
        )


def _tool_call_response(arguments, name="emit_job_description"):
    call = SimpleNamespace(id="call_1", function=SimpleNamespace(name=name, arguments=arguments))
    message = SimpleNamespace(content=None, tool_calls=[call])
    return _raw_response(
        choices=[SimpleNamespace(message=message, finish_reason="tool_calls")], model="x"
    )


async def test_already_parsed_tool_arguments_are_used_not_discarded():
    """Some gateways hand back `arguments` already decoded. Dropping it on the floor
    would turn a crash into silent data loss, which is strictly worse."""
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_tool_call_response({"title": "SRE"}), sent),
        capabilities=FakeCaps(),
    )

    reply = await client.complete(
        model="intake-jd", messages=[{"role": "user", "content": "hi"}], tools=[TOOL]
    )

    assert reply.tool_call_named("emit_job_description").arguments == {"title": "SRE"}


async def test_non_iterable_tool_calls_raises_llmerror():
    sent = []
    message = SimpleNamespace(content=None, tool_calls=7)
    bad = _raw_response(
        choices=[SimpleNamespace(message=message, finish_reason="tool_calls")], model="x"
    )
    client = LLMClient(openai_client=_openai_stub(bad, sent), capabilities=FakeCaps())

    with pytest.raises(LLMError) as exc:
        await client.complete(
            model="intake-jd", messages=[{"role": "user", "content": "hi"}], tools=[TOOL]
        )

    assert "intake-jd" in str(exc.value)


async def test_non_subscriptable_choices_raises_llmerror():
    sent = []
    # Truthy, so the `not choices` guard passes, but choices[0] is a TypeError.
    bad = _raw_response(choices=SimpleNamespace(), model="x")
    client = LLMClient(openai_client=_openai_stub(bad, sent), capabilities=FakeCaps())

    with pytest.raises(LLMError) as exc:
        await client.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}])

    assert "intake-jd" in str(exc.value)


async def test_cancellation_is_never_swallowed():
    """CancelledError is a BaseException and must survive the normalization layer,
    or a cancelled request turns into a bogus LLMError instead of unwinding."""

    class Cancelling:
        async def create(self, **kwargs):
            raise asyncio.CancelledError()

    client = LLMClient(
        openai_client=SimpleNamespace(chat=SimpleNamespace(completions=Cancelling())),
        capabilities=FakeCaps(),
    )

    with pytest.raises(asyncio.CancelledError):
        await client.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}])


async def test_invalid_tool_arguments_are_never_logged_verbatim():
    """Tool arguments carry candidate names, feedback and hiring signals. Only the
    shape of the payload may reach a log line."""
    sent = []
    leaky = '{"candidate_name": "Ada Lovelace", "feedback": "strong hire, ship it"'
    client = LLMClient(
        openai_client=_openai_stub(_tool_call_response(leaky), sent), capabilities=FakeCaps()
    )

    with structlog.testing.capture_logs() as logs:
        reply = await client.complete(
            model="intake-jd", messages=[{"role": "user", "content": "hi"}], tools=[TOOL]
        )

    rendered = json.dumps(logs)
    assert logs, "the malformed payload should still be reported"
    assert "Ada Lovelace" not in rendered
    assert "strong hire" not in rendered
    assert reply.tool_call_named("emit_job_description").arguments == {}


async def test_non_object_tool_arguments_are_never_logged_verbatim():
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_tool_call_response('["Ada Lovelace"]'), sent),
        capabilities=FakeCaps(),
    )

    with structlog.testing.capture_logs() as logs:
        reply = await client.complete(
            model="intake-jd", messages=[{"role": "user", "content": "hi"}], tools=[TOOL]
        )

    rendered = json.dumps(logs)
    assert logs
    assert "Ada Lovelace" not in rendered
    assert reply.tool_call_named("emit_job_description").arguments == {}


async def test_empty_tool_list_is_treated_as_no_tools():
    sent = []
    caps = FakeCaps(supported=False)
    client = LLMClient(openai_client=_openai_stub(_text_response("hello"), sent), capabilities=caps)

    reply = await client.complete(
        model="intake-jd", messages=[{"role": "user", "content": "hi"}], tools=[]
    )

    # An empty list must not reach build_emulation_instruction, which now raises.
    assert reply.text == "hello"
    assert reply.emulated_tools is False
    assert caps.asked == []
    assert "tools" not in sent[0]


# --- Tool shape is validated on both dispatch paths --------------------------

ANTHROPIC_TOOL = {
    "name": "emit_job_description",
    "description": "Return the structured job description.",
    "input_schema": {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    },
}


async def test_anthropic_shaped_tool_is_rejected_on_the_native_path():
    """The regression this guard exists for.

    A tool-capable alias used to skip validation entirely and put the spec into
    payload["tools"] verbatim, so an Anthropic-shaped schema left the process and
    came back as a provider 400. Nothing may be dispatched.
    """
    sent = []
    caps = FakeCaps(supported=True)
    client = LLMClient(openai_client=_openai_stub(_text_response("hi"), sent), capabilities=caps)

    with pytest.raises(ToolEmulationError) as exc:
        await client.complete(
            model="intake-jd",
            messages=[{"role": "user", "content": "hi"}],
            tools=[ANTHROPIC_TOOL],
        )

    message = str(exc.value)
    assert "input_schema" in message
    assert "emit_job_description" in message
    assert sent == [], "a malformed tool spec must never reach the gateway"


async def test_anthropic_shaped_tool_is_rejected_before_the_capability_probe():
    """Validation must not depend on the probe, which can fail open to tool-capable."""
    sent = []
    caps = FakeCaps(supported=True)
    client = LLMClient(openai_client=_openai_stub(_text_response("hi"), sent), capabilities=caps)

    with pytest.raises(ToolEmulationError):
        await client.complete(
            model="intake-jd",
            messages=[{"role": "user", "content": "hi"}],
            tools=[ANTHROPIC_TOOL],
        )

    assert caps.asked == []


async def test_both_paths_reject_an_anthropic_shaped_tool_identically():
    """Which alias is configured must not change whether the bug is caught."""
    errors = []
    for supported in (True, False):
        sent = []
        client = LLMClient(
            openai_client=_openai_stub(_text_response("hi"), sent),
            capabilities=FakeCaps(supported=supported),
        )
        with pytest.raises(ToolEmulationError) as exc:
            await client.complete(
                model="intake-jd",
                messages=[{"role": "user", "content": "hi"}],
                tools=[ANTHROPIC_TOOL],
            )
        errors.append(str(exc.value))
        assert sent == []

    assert errors[0] == errors[1]


async def test_a_tool_spec_that_is_not_a_dict_is_rejected_on_the_native_path():
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_text_response("hi"), sent), capabilities=FakeCaps()
    )

    with pytest.raises(ToolEmulationError):
        await client.complete(
            model="intake-jd",
            messages=[{"role": "user", "content": "hi"}],
            tools=["emit_job_description"],
        )

    assert sent == []


async def test_a_well_shaped_tool_still_reaches_the_gateway_untouched():
    """The guard must reject only malformed specs, not narrow what native tools accept."""
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_text_response("hi"), sent), capabilities=FakeCaps()
    )

    await client.complete(
        model="intake-jd", messages=[{"role": "user", "content": "hi"}], tools=[TOOL]
    )

    assert sent[0]["tools"] == [TOOL]


# --- tool_choice -------------------------------------------------------------
#
# Why this parameter exists: without it a model MAY answer a single-tool request
# in prose, and — measured at 8.75% on claude-haiku-4-5 — may emit a prose
# preamble BEFORE the tool call that eats the max_tokens budget and truncates the
# argument JSON. A truncated call still arrives as a correctly-named ToolCall
# carrying `arguments={}`, which a safety guardrail reads as a clean verdict.
# Forcing the tool suppresses the preamble and closes both paths.

FORCE_JD = {"type": "function", "function": {"name": "emit_job_description"}}


async def test_tool_choice_is_forwarded_to_the_gateway_verbatim():
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_tool_response("emit_job_description", {"title": "SRE"}), sent),
        capabilities=FakeCaps(),
    )

    await client.complete(
        model="intake-jd",
        messages=[{"role": "user", "content": "hi"}],
        tools=[TOOL],
        tool_choice=FORCE_JD,
    )

    assert sent[0]["tool_choice"] == FORCE_JD


async def test_tool_choice_is_absent_from_the_payload_by_default():
    """Today's behaviour is the default: no existing caller changes shape."""
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_tool_response("emit_job_description", {"title": "SRE"}), sent),
        capabilities=FakeCaps(),
    )

    await client.complete(
        model="intake-jd", messages=[{"role": "user", "content": "hi"}], tools=[TOOL]
    )

    assert "tool_choice" not in sent[0]


@pytest.mark.parametrize("choice", ["auto", "required"])
async def test_the_openai_string_forms_are_accepted(choice):
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_tool_response("emit_job_description", {"title": "SRE"}), sent),
        capabilities=FakeCaps(),
    )

    await client.complete(
        model="intake-jd",
        messages=[{"role": "user", "content": "hi"}],
        tools=[TOOL],
        tool_choice=choice,
    )

    assert sent[0]["tool_choice"] == choice


async def test_tool_choice_without_tools_is_rejected():
    """Forcing a tool with no tools is a caller bug, not a no-op.

    Silently dropping it is the failure mode that matters: the call site believes
    the tool is forced, the provider was never told, and the guarantee the caller
    is relying on is gone with nothing to show for it.
    """
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_text_response("hi"), sent), capabilities=FakeCaps()
    )

    with pytest.raises(LLMError) as exc:
        await client.complete(
            model="intake-jd",
            messages=[{"role": "user", "content": "hi"}],
            tool_choice=FORCE_JD,
        )

    assert "tool_choice" in str(exc.value)
    assert sent == []


async def test_tool_choice_with_an_empty_tool_list_is_rejected():
    """`tools=[]` is treated as no tools everywhere else in complete(); the
    rejection must follow that same truthiness check, not `is not None`."""
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_text_response("hi"), sent), capabilities=FakeCaps()
    )

    with pytest.raises(LLMError):
        await client.complete(
            model="intake-jd",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            tool_choice=FORCE_JD,
        )

    assert sent == []


async def test_anthropic_shaped_tool_choice_is_rejected():
    """Six un-migrated call sites in this repo still pass {'type': 'tool', 'name': ...}.

    Forwarding that verbatim is the same class of bug validate_tool_shape exists
    to catch: the gateway either 400s opaquely or ignores it, and the caller's
    forcing guarantee evaporates without a trace.
    """
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_text_response("hi"), sent), capabilities=FakeCaps()
    )

    with pytest.raises(LLMError) as exc:
        await client.complete(
            model="intake-jd",
            messages=[{"role": "user", "content": "hi"}],
            tools=[TOOL],
            tool_choice={"type": "tool", "name": "emit_job_description"},
        )

    assert "OpenAI" in str(exc.value)
    assert sent == []


async def test_tool_choice_none_is_rejected():
    """"none" has no faithful rendering on the emulated path, where the whole
    mechanism is an instruction mandating a tool-call JSON object. Rejecting it
    on BOTH paths keeps behaviour independent of which alias is configured;
    a caller that wants no tool call omits `tools`."""
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_text_response("hi"), sent), capabilities=FakeCaps()
    )

    with pytest.raises(LLMError):
        await client.complete(
            model="intake-jd",
            messages=[{"role": "user", "content": "hi"}],
            tools=[TOOL],
            tool_choice="none",
        )

    assert sent == []


async def test_forcing_a_tool_that_was_not_supplied_is_rejected():
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_text_response("hi"), sent), capabilities=FakeCaps()
    )

    with pytest.raises(LLMError) as exc:
        await client.complete(
            model="intake-jd",
            messages=[{"role": "user", "content": "hi"}],
            tools=[TOOL],
            tool_choice={"type": "function", "function": {"name": "emit_persona"}},
        )

    assert "emit_persona" in str(exc.value)
    assert sent == []


async def test_tool_choice_is_rejected_before_the_capability_probe():
    """Same rule as the tool-shape guard: a caller bug must not be caught (or
    missed) depending on what the probe answers."""
    caps = FakeCaps(supported=True)
    client = LLMClient(openai_client=_openai_stub(_text_response("hi"), []), capabilities=caps)

    with pytest.raises(LLMError):
        await client.complete(
            model="intake-jd",
            messages=[{"role": "user", "content": "hi"}],
            tool_choice=FORCE_JD,
        )

    assert caps.asked == []


async def test_an_unknown_tool_choice_value_is_rejected():
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_text_response("hi"), sent), capabilities=FakeCaps()
    )

    with pytest.raises(LLMError):
        await client.complete(
            model="intake-jd",
            messages=[{"role": "user", "content": "hi"}],
            tools=[TOOL],
            tool_choice="emit_job_description",
        )

    assert sent == []


# --- tool_choice on the emulated path ----------------------------------------

OTHER_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_persona",
        "description": "Return the persona.",
        "parameters": {"type": "object", "properties": {"tone": {"type": "string"}}},
    },
}


async def test_emulation_narrows_to_the_forced_tool():
    """Emulation forces *a* tool by construction, but with several supplied it
    lets the model pick. A named tool_choice must narrow the rendered instruction
    to that one, or "forced" means something weaker here than on the native path.
    """
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_text_response('{"title": "SRE"}'), sent),
        capabilities=FakeCaps(supported=False),
    )

    reply = await client.complete(
        model="intake-jd-local",
        messages=[{"role": "user", "content": "hi"}],
        tools=[TOOL, OTHER_TOOL],
        tool_choice=FORCE_JD,
    )

    instruction = sent[0]["messages"][0]["content"]
    assert "emit_job_description" in instruction
    assert "emit_persona" not in instruction
    # Single-tool rendering: no {"name": ..., "arguments": ...} envelope required,
    # so the bare object the model returned parses against the forced schema.
    assert reply.tool_call_named("emit_job_description").arguments == {"title": "SRE"}


async def test_tool_choice_never_reaches_a_model_that_cannot_do_native_tools():
    """The emulated path sends response_format, not tools — a tool_choice key
    alongside it is a parameter the provider was never going to honour."""
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(_text_response('{"title": "SRE"}'), sent),
        capabilities=FakeCaps(supported=False),
    )

    await client.complete(
        model="intake-jd-local",
        messages=[{"role": "user", "content": "hi"}],
        tools=[TOOL],
        tool_choice=FORCE_JD,
    )

    assert "tool_choice" not in sent[0]
    assert "tools" not in sent[0]
    assert sent[0]["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("choice", ["auto", "required"])
async def test_the_string_forms_are_a_no_op_on_the_emulated_path(choice):
    """Emulation already yields exactly one call, so both are already satisfied.
    Neither may narrow or drop a tool."""
    sent = []
    client = LLMClient(
        openai_client=_openai_stub(
            _text_response('{"name": "emit_persona", "arguments": {"tone": "warm"}}'), sent
        ),
        capabilities=FakeCaps(supported=False),
    )

    reply = await client.complete(
        model="intake-jd-local",
        messages=[{"role": "user", "content": "hi"}],
        tools=[TOOL, OTHER_TOOL],
        tool_choice=choice,
    )

    instruction = sent[0]["messages"][0]["content"]
    assert "emit_job_description" in instruction
    assert "emit_persona" in instruction
    assert reply.tool_call_named("emit_persona").arguments == {"tone": "warm"}
