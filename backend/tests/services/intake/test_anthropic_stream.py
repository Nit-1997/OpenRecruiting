"""Tests for the Anthropic streaming wrapper used by text_runner."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from app.services.intake.anthropic_stream import stream_llm_turn


class _FakeStream:
    """Async-iterable stub that emits Anthropic-like SSE events."""

    def __init__(self, events: list):
        self._events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __aiter__(self):
        async def gen():
            for ev in self._events:
                yield ev
        return gen()

    async def get_final_message(self):
        return MagicMock(
            content=[MagicMock(type="text", text="hello world")],
            stop_reason="end_turn",
        )


def _text_delta(text: str):
    return MagicMock(
        type="content_block_delta",
        delta=MagicMock(type="text_delta", text=text),
    )


def _tool_use_block_start(tool_name: str, tool_id: str):
    # MagicMock's `name` kwarg sets the mock's repr name, not the attribute.
    # Use configure_mock to set `name` as a real attribute.
    block = MagicMock(type="tool_use", id=tool_id, input={})
    block.configure_mock(**{"name": tool_name})
    return MagicMock(
        type="content_block_start",
        content_block=block,
    )


def _tool_use_input_delta(partial_json: str):
    return MagicMock(
        type="content_block_delta",
        delta=MagicMock(type="input_json_delta", partial_json=partial_json),
    )


def _content_block_stop():
    return MagicMock(type="content_block_stop")


@pytest.mark.asyncio
async def test_stream_yields_text_chunks():
    fake_stream = _FakeStream([
        _text_delta("Hello "),
        _text_delta("there"),
        _content_block_stop(),
    ])
    client = MagicMock()
    client.messages.stream = MagicMock(return_value=fake_stream)

    out = []
    async for kind, payload in stream_llm_turn(
        client=client, model="claude-sonnet-4-6",
        system="sys", messages=[{"role": "user", "content": "hi"}],
        tools=[],
    ):
        out.append((kind, payload))

    text_chunks = [p for k, p in out if k == "text"]
    assert text_chunks == ["Hello ", "there"]
    done = [p for k, p in out if k == "done"]
    assert len(done) == 1
    assert done[0]["text"] == "hello world"


@pytest.mark.asyncio
async def test_stream_emits_tool_call_with_assembled_input():
    fake_stream = _FakeStream([
        _tool_use_block_start(tool_name="update_answer", tool_id="toolu_1"),
        _tool_use_input_delta('{"qid":"q4'),
        _tool_use_input_delta('_must_haves","text":"Python"}'),
        _content_block_stop(),
    ])
    client = MagicMock()
    client.messages.stream = MagicMock(return_value=fake_stream)

    events = []
    async for kind, payload in stream_llm_turn(
        client=client, model="x",
        system="sys", messages=[{"role": "user", "content": "hi"}],
        tools=[{"name": "update_answer"}],
    ):
        events.append((kind, payload))

    tool_calls = [p for k, p in events if k == "tool_call"]
    assert len(tool_calls) == 1
    tc = tool_calls[0]
    assert tc["name"] == "update_answer"
    assert tc["id"] == "toolu_1"
    assert tc["input"] == {"qid": "q4_must_haves", "text": "Python"}
