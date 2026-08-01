import pytest

from app.services.intake.parse_intent_service import parse_role_intent


class _FakeBlock:
    def __init__(self, name, input):
        self.type = "tool_use"
        self.name = name
        self.input = input


class _FakeMessage:
    def __init__(self, blocks):
        self.content = blocks


class _FakeMessages:
    def __init__(self, message=None, raises=None):
        self._message = message
        self._raises = raises

    async def create(self, **kwargs):
        if self._raises:
            raise self._raises
        return self._message


class _FakeClient:
    def __init__(self, message=None, raises=None):
        self.messages = _FakeMessages(message=message, raises=raises)


@pytest.mark.asyncio
async def test_full_extraction():
    client = _FakeClient(
        message=_FakeMessage([
            _FakeBlock("emit_role_fields", {
                "intent": "create_role",
                "role_name": "Senior Backend Engineer",
                "exp_min": 7, "exp_max": 11, "location": "Remote · US",
            })
        ])
    )
    out = await parse_role_intent(client, "need a senior backend eng, 7-11 yrs, remote US")
    assert out == {
        "role_name": "Senior Backend Engineer",
        "exp_min": 7, "exp_max": 11, "location": "Remote · US",
        "intent": "create_role", "list_status": None,
    }


@pytest.mark.asyncio
async def test_partial_extraction_missing_fields_are_none():
    client = _FakeClient(
        message=_FakeMessage([_FakeBlock("emit_role_fields", {"intent": "create_role", "role_name": "Data Scientist"})])
    )
    out = await parse_role_intent(client, "hire a data scientist")
    assert out == {"role_name": "Data Scientist", "exp_min": None, "exp_max": None, "location": None, "intent": "create_role", "list_status": None}


@pytest.mark.asyncio
async def test_no_tool_call_yields_all_none():
    client = _FakeClient(message=_FakeMessage([]))
    out = await parse_role_intent(client, "blah blah")
    assert out == {"role_name": None, "exp_min": None, "exp_max": None, "location": None, "intent": "other", "list_status": None}


@pytest.mark.asyncio
async def test_llm_exception_yields_all_none():
    client = _FakeClient(raises=RuntimeError("boom"))
    out = await parse_role_intent(client, "create a role")
    assert out == {"role_name": None, "exp_min": None, "exp_max": None, "location": None, "intent": "other", "list_status": None}


@pytest.mark.asyncio
async def test_product_manager_san_francisco_plumbing():
    """Plumbing test: tool input wired through correctly for PM+location phrase."""
    client = _FakeClient(
        message=_FakeMessage([
            _FakeBlock("emit_role_fields", {
                "intent": "create_role",
                "role_name": "Product Manager",
                "location": "San Francisco",
            })
        ])
    )
    out = await parse_role_intent(
        client, "create a new req in San Francisco for a Product Manager role"
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
async def test_non_role_query_returns_all_none():
    """Plumbing test: all-null tool response (non-role query) maps to all-None dict."""
    client = _FakeClient(
        message=_FakeMessage([_FakeBlock("emit_role_fields", {})])
    )
    out = await parse_role_intent(client, "show me pending intakes")
    assert out == {"role_name": None, "exp_min": None, "exp_max": None, "location": None, "intent": "other", "list_status": None}


@pytest.mark.asyncio
async def test_exp_min_only_extraction():
    """Plumbing: '3+ years' → exp_min=3, exp_max absent."""
    client = _FakeClient(
        message=_FakeMessage([
            _FakeBlock("emit_role_fields", {
                "intent": "create_role",
                "role_name": "iOS Developer",
                "exp_min": 3,
            })
        ])
    )
    out = await parse_role_intent(client, "opening for iOS developer 3+ years")
    assert out == {
        "role_name": "iOS Developer",
        "exp_min": 3,
        "exp_max": None,
        "location": None,
        "intent": "create_role",
        "list_status": None,
    }


@pytest.mark.asyncio
async def test_list_sessions_pending_intent():
    """list_sessions intent with pending status flows through correctly."""
    client = _FakeClient(
        message=_FakeMessage([
            _FakeBlock("emit_role_fields", {
                "intent": "list_sessions",
                "list_status": "pending",
            })
        ])
    )
    out = await parse_role_intent(client, "show me pending intakes")
    assert out == {
        "role_name": None,
        "exp_min": None,
        "exp_max": None,
        "location": None,
        "intent": "list_sessions",
        "list_status": "pending",
    }


@pytest.mark.asyncio
async def test_list_sessions_all_intent():
    """list_sessions with no status filter → list_status='all'."""
    client = _FakeClient(
        message=_FakeMessage([
            _FakeBlock("emit_role_fields", {
                "intent": "list_sessions",
                "list_status": "all",
            })
        ])
    )
    out = await parse_role_intent(client, "list all my roles")
    assert out == {
        "role_name": None,
        "exp_min": None,
        "exp_max": None,
        "location": None,
        "intent": "list_sessions",
        "list_status": "all",
    }


@pytest.mark.asyncio
async def test_invalid_intent_value_falls_back_to_other():
    """Unknown intent string from LLM → 'other'."""
    client = _FakeClient(
        message=_FakeMessage([
            _FakeBlock("emit_role_fields", {
                "intent": "something_random",
            })
        ])
    )
    out = await parse_role_intent(client, "do something")
    assert out["intent"] == "other"
    assert out["list_status"] is None


@pytest.mark.asyncio
async def test_invalid_list_status_falls_back_to_none():
    """Unknown list_status from LLM → None."""
    client = _FakeClient(
        message=_FakeMessage([
            _FakeBlock("emit_role_fields", {
                "intent": "list_sessions",
                "list_status": "unknown_status",
            })
        ])
    )
    out = await parse_role_intent(client, "show my things")
    assert out["intent"] == "list_sessions"
    assert out["list_status"] is None
