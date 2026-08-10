"""parse_role_intent against llm-core's FakeLLM — no provider shapes anywhere."""
import pytest
from llm_core.errors import LLMError

from app.services.intake.parse_intent_service import parse_role_intent

FORCED = {"type": "function", "function": {"name": "emit_role_fields"}}

ALL_NONE = {
    "role_name": None,
    "exp_min": None,
    "exp_max": None,
    "location": None,
    "intent": "other",
    "list_status": None,
}


@pytest.mark.asyncio
async def test_full_extraction(fake_llm):
    fake_llm.queue_tool_call(
        "emit_role_fields",
        {
            "intent": "create_role",
            "role_name": "Senior Backend Engineer",
            "exp_min": 7,
            "exp_max": 11,
            "location": "Remote · US",
        },
    )
    out = await parse_role_intent(fake_llm, "need a senior backend eng, 7-11 yrs, remote US")
    assert out == {
        "role_name": "Senior Backend Engineer",
        "exp_min": 7, "exp_max": 11, "location": "Remote · US",
        "intent": "create_role", "list_status": None,
    }


@pytest.mark.asyncio
async def test_partial_extraction_missing_fields_are_none(fake_llm):
    fake_llm.queue_tool_call(
        "emit_role_fields", {"intent": "create_role", "role_name": "Data Scientist"}
    )
    out = await parse_role_intent(fake_llm, "hire a data scientist")
    assert out == {"role_name": "Data Scientist", "exp_min": None, "exp_max": None, "location": None, "intent": "create_role", "list_status": None}


@pytest.mark.asyncio
async def test_no_tool_call_yields_all_none(fake_llm):
    """Defence in depth. The tool is forced, so a prose reply should be
    unreachable; when it happens anyway the recruiter gets an empty form rather
    than an error, which is what the empty-content case produced before."""
    fake_llm.queue_text("I'm not sure what you mean.")
    out = await parse_role_intent(fake_llm, "blah blah")
    assert out == ALL_NONE


@pytest.mark.asyncio
async def test_llm_exception_yields_all_none(fake_llm):
    fake_llm.queue_error(LLMError("gateway 500", alias="parse-role-intent", status=500))
    out = await parse_role_intent(fake_llm, "create a role")
    assert out == ALL_NONE


@pytest.mark.asyncio
async def test_a_reply_naming_another_tool_yields_all_none(fake_llm):
    """tool_call_named is name-matched, so a wrong-tool reply degrades the same
    way a prose reply does — the block loop it replaced behaved identically."""
    fake_llm.queue_tool_call("some_other_tool", {"intent": "create_role"})
    out = await parse_role_intent(fake_llm, "create a role")
    assert out == ALL_NONE


@pytest.mark.asyncio
async def test_product_manager_san_francisco_plumbing(fake_llm):
    """Plumbing test: tool input wired through correctly for PM+location phrase."""
    fake_llm.queue_tool_call(
        "emit_role_fields",
        {
            "intent": "create_role",
            "role_name": "Product Manager",
            "location": "San Francisco",
        },
    )
    out = await parse_role_intent(
        fake_llm, "create a new req in San Francisco for a Product Manager role"
    )
    assert out == {
        "role_name": "Product Manager",
        "exp_min": None,
        "exp_max": None,
        "location": "San Francisco",
        "intent": "create_role",
        "list_status": None,
    }


@pytest.mark.asyncio
async def test_non_role_query_returns_all_none(fake_llm):
    """Plumbing test: all-null tool response (non-role query) maps to all-None dict."""
    fake_llm.queue_tool_call("emit_role_fields", {})
    out = await parse_role_intent(fake_llm, "show me pending intakes")
    assert out == ALL_NONE


@pytest.mark.asyncio
async def test_exp_min_only_extraction(fake_llm):
    """Plumbing: '3+ years' → exp_min=3, exp_max absent."""
    fake_llm.queue_tool_call(
        "emit_role_fields",
        {"intent": "create_role", "role_name": "iOS Developer", "exp_min": 3},
    )
    out = await parse_role_intent(fake_llm, "opening for iOS developer 3+ years")
    assert out == {
        "role_name": "iOS Developer",
        "exp_min": 3,
        "exp_max": None,
        "location": None,
        "intent": "create_role",
        "list_status": None,
    }


@pytest.mark.asyncio
async def test_list_sessions_pending_intent(fake_llm):
    """list_sessions intent with pending status flows through correctly."""
    fake_llm.queue_tool_call(
        "emit_role_fields", {"intent": "list_sessions", "list_status": "pending"}
    )
    out = await parse_role_intent(fake_llm, "show me pending intakes")
    assert out == {
        "role_name": None,
        "exp_min": None,
        "exp_max": None,
        "location": None,
        "intent": "list_sessions",
        "list_status": "pending",
    }


@pytest.mark.asyncio
async def test_list_sessions_all_intent(fake_llm):
    """list_sessions with no status filter → list_status='all'."""
    fake_llm.queue_tool_call(
        "emit_role_fields", {"intent": "list_sessions", "list_status": "all"}
    )
    out = await parse_role_intent(fake_llm, "list all my roles")
    assert out == {
        "role_name": None,
        "exp_min": None,
        "exp_max": None,
        "location": None,
        "intent": "list_sessions",
        "list_status": "all",
    }


@pytest.mark.asyncio
async def test_invalid_intent_value_falls_back_to_other(fake_llm):
    """Unknown intent string from LLM → 'other'."""
    fake_llm.queue_tool_call("emit_role_fields", {"intent": "something_random"})
    out = await parse_role_intent(fake_llm, "do something")
    assert out["intent"] == "other"
    assert out["list_status"] is None


@pytest.mark.asyncio
async def test_invalid_list_status_falls_back_to_none(fake_llm):
    """Unknown list_status from LLM → None."""
    fake_llm.queue_tool_call(
        "emit_role_fields", {"intent": "list_sessions", "list_status": "unknown_status"}
    )
    out = await parse_role_intent(fake_llm, "show my things")
    assert out["intent"] == "list_sessions"
    assert out["list_status"] is None


@pytest.mark.asyncio
async def test_sends_the_alias_a_forced_openai_shaped_tool(fake_llm):
    """Replaces the coverage the old tool_choice assertion gave.

    FakeLLM runs the same validate_tool_shape/validate_tool_choice the real
    client does, so an Anthropic-shaped spec or an Anthropic-shaped choice would
    already have raised before reaching these assertions.
    """
    fake_llm.queue_tool_call("emit_role_fields", {"intent": "other"})
    await parse_role_intent(fake_llm, "hello")

    call = fake_llm.calls[0]
    assert call["model"] == "parse-role-intent"      # was "claude-haiku-4-5-20251001"
    assert call["max_tokens"] == 400
    assert call["tool_choice"] == FORCED
    assert call["system"].startswith("You classify a recruiter's free-text message")
    assert [t["function"]["name"] for t in call["tools"]] == ["emit_role_fields"]
    assert call["tools"][0]["type"] == "function"
    assert call["messages"] == [{"role": "user", "content": "hello"}]
