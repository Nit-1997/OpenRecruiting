import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from llm_core.client import LLMClient
from llm_core.errors import LLMError

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
