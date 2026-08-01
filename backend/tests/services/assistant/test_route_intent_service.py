import pytest

from app.services.assistant.route_intent_service import classify_route_intent


class _FakeBlock:
    def __init__(self, intent):
        self.type = "tool_use"
        self.name = "emit_route"
        self.input = {"intent": intent} if intent is not None else {}


class _FakeMessage:
    def __init__(self, blocks):
        self.content = blocks


class _FakeMessages:
    def __init__(self, message=None, raises=None):
        self._message = message
        self._raises = raises
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        if self._raises:
            raise self._raises
        return self._message


class _FakeClient:
    def __init__(self, message=None, raises=None):
        self.messages = _FakeMessages(message=message, raises=raises)


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["browse_roles", "intake_call", "out_of_scope"])
async def test_each_intent_flows_through(intent):
    client = _FakeClient(message=_FakeMessage([_FakeBlock(intent)]))
    assert await classify_route_intent(client, "whatever") == intent


@pytest.mark.asyncio
async def test_llm_exception_is_out_of_scope():
    client = _FakeClient(raises=RuntimeError("boom"))
    assert await classify_route_intent(client, "create a role") == "out_of_scope"


@pytest.mark.asyncio
async def test_unknown_intent_value_is_out_of_scope():
    client = _FakeClient(message=_FakeMessage([_FakeBlock("something_random")]))
    assert await classify_route_intent(client, "do a thing") == "out_of_scope"


@pytest.mark.asyncio
async def test_no_tool_call_is_out_of_scope():
    client = _FakeClient(message=_FakeMessage([]))
    assert await classify_route_intent(client, "hello") == "out_of_scope"


@pytest.mark.asyncio
async def test_missing_intent_key_is_out_of_scope():
    client = _FakeClient(message=_FakeMessage([_FakeBlock(None)]))
    assert await classify_route_intent(client, "hmm") == "out_of_scope"


@pytest.mark.asyncio
async def test_wrong_tool_name_is_out_of_scope():
    class _OtherBlock:
        type = "tool_use"
        name = "some_other_tool"
        input = {"intent": "browse_roles"}

    client = _FakeClient(message=_FakeMessage([_OtherBlock()]))
    assert await classify_route_intent(client, "show roles") == "out_of_scope"


@pytest.mark.asyncio
async def test_calls_llm_with_expected_model_and_tool():
    client = _FakeClient(message=_FakeMessage([_FakeBlock("browse_roles")]))
    await classify_route_intent(client, "show roles")
    kw = client.messages.last_kwargs
    assert kw["model"] == "claude-sonnet-4-6"
    assert kw["tool_choice"] == {"type": "tool", "name": "emit_route"}
    assert [t["name"] for t in kw["tools"]] == ["emit_route"]
    assert kw["messages"] == [{"role": "user", "content": "show roles"}]
