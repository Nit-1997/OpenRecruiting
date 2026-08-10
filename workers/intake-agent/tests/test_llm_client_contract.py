"""The gateway client's response contract.

Both live call sites (pipeline.py:100 and :120) feed the result straight into
json.loads via parse_json_response. OpenAI returns `content: null` when the model
produces nothing, so coercing it to "" once in the client is what keeps a
degraded reply failing as an obvious empty-parse at the call site rather than as
`NoneType has no attribute strip` somewhere further down.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.clients.llm import LLMGatewayClient


def _response(payload):
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json = MagicMock(return_value=payload)
    return r


@pytest.mark.asyncio
async def test_a_null_content_becomes_an_empty_string():
    client = LLMGatewayClient()
    client._client = AsyncMock()
    client._client.is_closed = False
    client._client.post.return_value = _response(
        {"choices": [{"message": {"content": None}}], "usage": {}}
    )

    out = await client.call("hi", model="sonnet")

    assert out == "", "None would break every call site's string handling"


@pytest.mark.asyncio
async def test_a_normal_reply_passes_through():
    client = LLMGatewayClient()
    client._client = AsyncMock()
    client._client.is_closed = False
    client._client.post.return_value = _response(
        {"choices": [{"message": {"content": '{"rounds": []}'}}], "usage": {}}
    )

    out = await client.call("hi", model="sonnet")

    assert out == '{"rounds": []}'


@pytest.mark.asyncio
async def test_the_alias_is_sent_not_a_provider_model_id():
    client = LLMGatewayClient()
    client._client = AsyncMock()
    client._client.is_closed = False
    client._client.post.return_value = _response(
        {"choices": [{"message": {"content": "ok"}}], "usage": {}}
    )

    await client.call("hi", model="sonnet")

    sent = client._client.post.call_args.kwargs["json"]
    assert sent["model"] == "intake-agent-sonnet"
    assert "claude" not in sent["model"], "a provider model id would bypass the gateway's map"
