from llm_core.types import LLMReply, ToolCall


def test_tool_call_named_finds_matching_call():
    reply = LLMReply(
        text="",
        tool_calls=[
            ToolCall(id="c1", name="emit_job_description", arguments={"title": "SRE"}),
            ToolCall(id="c2", name="mark_status", arguments={"status": "done"}),
        ],
        finish_reason="tool_calls",
        model="intake-jd",
    )

    found = reply.tool_call_named("mark_status")

    assert found is not None
    assert found.id == "c2"
    assert found.arguments == {"status": "done"}


def test_tool_call_named_returns_none_when_absent():
    reply = LLMReply(text="hi", tool_calls=[], finish_reason="stop", model="intake-jd")

    assert reply.tool_call_named("nope") is None


def test_reply_defaults_are_safe():
    reply = LLMReply(text="hi", model="intake-jd")

    assert reply.tool_calls == []
    assert reply.finish_reason is None
    assert reply.emulated_tools is False
