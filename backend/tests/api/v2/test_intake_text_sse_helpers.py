"""Unit tests for the SSE helpers + stream generators in intake_text_messages,
covering the text/tool/done branches and both error branches."""

import json
from unittest.mock import patch

import pytest

from app.api.v2.routers import intake_text_messages as itm
from app.services.intake.text_runner import ModalityConflictError


def _collect_sse(chunks):
    """Parse a list of raw SSE strings into [(event, data_obj)]."""
    out = []
    for c in chunks:
        lines = c.strip().split("\n")
        event = next(l[len("event: "):] for l in lines if l.startswith("event: "))
        data = next(l[len("data: "):] for l in lines if l.startswith("data: "))
        out.append((event, json.loads(data)))
    return out


def test_sse_event_json_encodes_data():
    out = itm._sse_event("text", "hello\nworld")
    assert out.startswith("event: text\n")
    assert '"hello\\nworld"' in out
    assert out.endswith("\n\n")


@pytest.mark.asyncio
async def test_sse_stream_text_tool_done():
    async def fake_turn(**kwargs):
        yield ("text", "Hi ")
        yield ("tool_call", {"name": "search", "input": {"q": "x"}})
        yield ("done", {"text": "Hi", "stop_reason": "end_turn"})

    with patch.object(itm, "run_text_turn", fake_turn):
        chunks = [c async for c in itm._sse_stream(None, None, "s1", "hello")]
    events = _collect_sse(chunks)
    assert ("text", "Hi ") in events
    assert ("tool", {"name": "search", "args": {"q": "x"}}) in events
    assert events[-1][0] == "done"


@pytest.mark.asyncio
async def test_sse_stream_modality_conflict_error():
    async def fake_turn(**kwargs):
        raise ModalityConflictError("voice active")
        yield  # pragma: no cover

    with patch.object(itm, "run_text_turn", fake_turn):
        chunks = [c async for c in itm._sse_stream(None, None, "s1", "hello")]
    events = _collect_sse(chunks)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "modality_conflict"


@pytest.mark.asyncio
async def test_sse_stream_generic_error():
    async def fake_turn(**kwargs):
        raise RuntimeError("boom" * 200)
        yield  # pragma: no cover

    with patch.object(itm, "run_text_turn", fake_turn):
        chunks = [c async for c in itm._sse_stream(None, None, "s1", "hello")]
    events = _collect_sse(chunks)
    assert events[-1][1]["code"] == "internal_error"
    assert len(events[-1][1]["message"]) <= 300


@pytest.mark.asyncio
async def test_sse_opening_stream_text_done():
    async def fake_open(**kwargs):
        yield ("text", "Welcome")
        yield ("done", {"text": "Welcome"})

    with patch.object(itm, "run_text_opening", fake_open):
        chunks = [c async for c in itm._sse_opening_stream(None, None, "s1")]
    events = _collect_sse(chunks)
    assert ("text", "Welcome") in events
    assert events[-1][0] == "done"


@pytest.mark.asyncio
async def test_sse_opening_stream_generic_error():
    async def fake_open(**kwargs):
        raise RuntimeError("kaboom")
        yield  # pragma: no cover

    with patch.object(itm, "run_text_opening", fake_open):
        chunks = [c async for c in itm._sse_opening_stream(None, None, "s1")]
    events = _collect_sse(chunks)
    assert events[-1][1]["code"] == "internal_error"
