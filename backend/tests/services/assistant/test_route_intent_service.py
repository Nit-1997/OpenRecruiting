"""classify_route_intent against llm-core's FakeLLM — no provider shapes anywhere."""
import pytest
from llm_core.errors import LLMError

from app.services.assistant.route_intent_service import classify_route_intent

FORCED = {"type": "function", "function": {"name": "emit_route"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["browse_roles", "intake_call", "debrief", "out_of_scope"])
async def test_each_intent_flows_through(fake_llm, intent):
    fake_llm.queue_tool_call("emit_route", {"intent": intent})
    assert await classify_route_intent(fake_llm, "whatever") == intent


@pytest.mark.asyncio
async def test_llm_exception_is_out_of_scope(fake_llm):
    fake_llm.queue_error(LLMError("gateway 503", alias="route-intent", status=503))
    assert await classify_route_intent(fake_llm, "create a role") == "out_of_scope"


@pytest.mark.asyncio
async def test_unknown_intent_value_is_out_of_scope(fake_llm):
    fake_llm.queue_tool_call("emit_route", {"intent": "something_random"})
    assert await classify_route_intent(fake_llm, "do a thing") == "out_of_scope"


@pytest.mark.asyncio
async def test_no_tool_call_is_out_of_scope(fake_llm):
    """Defence in depth behind the forced tool. If forcing ever stops working the
    recruiter gets the routing chips rather than an error."""
    fake_llm.queue_text("Hello! How can I help?")
    assert await classify_route_intent(fake_llm, "hello") == "out_of_scope"


@pytest.mark.asyncio
async def test_missing_intent_key_is_out_of_scope(fake_llm):
    """Also the shape a truncated call arrives in: llm_core surfaces unparseable
    argument JSON as arguments={}. 64 max_tokens makes that the realistic
    truncation here, not an exotic one."""
    fake_llm.queue_tool_call("emit_route", {})
    assert await classify_route_intent(fake_llm, "hmm") == "out_of_scope"


@pytest.mark.asyncio
async def test_wrong_tool_name_is_out_of_scope(fake_llm):
    fake_llm.queue_tool_call("some_other_tool", {"intent": "browse_roles"})
    assert await classify_route_intent(fake_llm, "show roles") == "out_of_scope"


@pytest.mark.asyncio
async def test_calls_llm_with_expected_alias_and_forced_tool(fake_llm):
    fake_llm.queue_tool_call("emit_route", {"intent": "browse_roles"})
    await classify_route_intent(fake_llm, "show roles")

    call = fake_llm.calls[0]
    assert call["model"] == "route-intent"            # was "claude-sonnet-4-6"
    assert call["max_tokens"] == 64
    assert call["tool_choice"] == FORCED
    assert [t["function"]["name"] for t in call["tools"]] == ["emit_route"]
    assert call["tools"][0]["type"] == "function"
    assert call["messages"] == [{"role": "user", "content": "show roles"}]
