"""Tests for the text agent loop (text_runner.run_text_turn)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest

from app.services.intake import text_runner
from app.services.intake.text_runner import (
    run_text_turn,
    run_text_opening,
    ModalityConflictError,
    _MAX_TOOL_ITERATIONS,
)


@pytest.fixture
def fake_session():
    return {
        "id": "sess-1",
        "requisition_id": "req-1",
        "user_id": "user-1",
        "organization_id": "org-1",
        "status": "ready",
        "active_modality": None,
        "form_data": {"role_name": "Senior BE"},
        "questions_version": "v1-2026-05-27",
        "questions_snapshot": [],
        "current_answers": {},
        "turns": [],
    }


@pytest.fixture
def mock_supabase():
    client = MagicMock()
    chain = MagicMock()
    chain.update.return_value = chain
    chain.eq.return_value = chain
    chain.execute_async = AsyncMock(return_value=MagicMock(data=[{"id": "sess-1"}]))
    client.table.return_value = chain
    return client, chain


async def _collect(gen):
    out = []
    async for ev in gen:
        out.append(ev)
    return out


@pytest.mark.asyncio
async def test_run_text_turn_rejects_when_voice_active(fake_session, mock_supabase):
    client, _ = mock_supabase
    fake_session["active_modality"] = "voice"
    with patch("app.services.intake.text_runner.aload_session", new=AsyncMock(return_value=fake_session)):
        gen = run_text_turn(
            supabase_client=client, llm=MagicMock(),
            model="x", session_id="sess-1", user_message="hi",
        )
        with pytest.raises(ModalityConflictError):
            await _collect(gen)


@pytest.mark.asyncio
async def test_run_text_opening_greets_without_user_turn(fake_session, mock_supabase):
    """Opening streams a greeting and persists ONLY the assistant turn (no user turn)."""
    client, _ = mock_supabase

    async def fake_stream(**kwargs):
        yield ("text", "Hey, Scout here ")
        yield ("text", "— let's nail the Senior BE role.")
        yield ("done", {"text": "...", "stop_reason": "stop"})

    mock_append = AsyncMock(return_value={"idx": 0, "role": "assistant", "modality": "text"})

    with patch("app.services.intake.text_runner.aload_session", new=AsyncMock(return_value=fake_session)), \
         patch("app.services.intake.text_runner.append_turn_for_session", new=mock_append), \
         patch("app.services.intake.text_runner.stream_llm_turn", new=fake_stream), \
         patch("app.services.intake.text_runner.build_dynamic_prompt", return_value="SYS"):
        events = await _collect(run_text_opening(
            supabase_client=client, llm=MagicMock(),
            model="claude-sonnet-4-6", session_id="sess-1",
        ))

    text_events = [p for k, p in events if k == "text"]
    assert text_events == ["Hey, Scout here ", "— let's nail the Senior BE role."]
    # Exactly one persisted turn, and it's the assistant greeting (no user turn).
    assert mock_append.call_count == 1
    assert mock_append.call_args.kwargs["role"] == "assistant"
    done = [p for k, p in events if k == "done"]
    assert done and done[0]["assistant_turn_idx"] == 0


@pytest.mark.asyncio
async def test_run_text_opening_noop_when_agent_spoke_last(fake_session, mock_supabase):
    """Floor rule: if the agent's message is the last turn, the recruiter has the
    floor — the opening must stay silent (no double-message)."""
    client, _ = mock_supabase
    fake_session["turns"] = [
        {"idx": 0, "role": "user", "content": "hi", "modality": "voice"},
        {"idx": 1, "role": "assistant", "content": "Hi! Tell me about the role.", "modality": "voice"},
    ]
    mock_append = AsyncMock()

    with patch("app.services.intake.text_runner.aload_session", new=AsyncMock(return_value=fake_session)), \
         patch("app.services.intake.text_runner.append_turn_for_session", new=mock_append), \
         patch("app.services.intake.text_runner.build_dynamic_prompt", return_value="SYS"):
        events = await _collect(run_text_opening(
            supabase_client=client, llm=MagicMock(),
            model="claude-sonnet-4-6", session_id="sess-1",
        ))

    assert mock_append.call_count == 0
    done = [p for k, p in events if k == "done"]
    assert done and done[0].get("skipped") is True


@pytest.mark.asyncio
async def test_run_text_opening_continues_when_recruiter_spoke_last(fake_session, mock_supabase):
    """Handoff floor rule: voice→text where the recruiter spoke last must make the
    agent CONTINUE — respond to the existing conversation (seeded with prior turns)
    and persist the assistant turn. This is the 'same agent picks up' behavior."""
    client, _ = mock_supabase
    fake_session["turns"] = [
        {"idx": 0, "role": "user", "content": "Yeah.", "modality": "voice"},
        {"idx": 1, "role": "user", "content": "for PRD and collaboration.", "modality": "voice"},
    ]

    seen_messages = {}

    async def fake_stream(**kwargs):
        seen_messages["messages"] = kwargs.get("messages")
        yield ("text", "Got it — PRD and cross-team. ")
        yield ("text", "How are the four rounds structured?")
        yield ("done", {"text": "...", "stop_reason": "stop"})

    mock_append = AsyncMock(return_value={"idx": 2, "role": "assistant", "modality": "text"})

    with patch("app.services.intake.text_runner.aload_session", new=AsyncMock(return_value=fake_session)), \
         patch("app.services.intake.text_runner.append_turn_for_session", new=mock_append), \
         patch("app.services.intake.text_runner.stream_llm_turn", new=fake_stream), \
         patch("app.services.intake.text_runner.build_dynamic_prompt", return_value="SYS"):
        events = await _collect(run_text_opening(
            supabase_client=client, llm=MagicMock(),
            model="claude-sonnet-4-6", session_id="sess-1",
        ))

    # Seeded with the real prior conversation (both user turns), ending on user.
    assert seen_messages["messages"] == [
        {"role": "user", "content": "Yeah."},
        {"role": "user", "content": "for PRD and collaboration."},
    ]
    # Persisted exactly the assistant continuation turn (no new user turn).
    assert mock_append.call_count == 1
    assert mock_append.call_args.kwargs["role"] == "assistant"
    text_events = [p for k, p in events if k == "text"]
    assert text_events == ["Got it — PRD and cross-team. ", "How are the four rounds structured?"]
    done = [p for k, p in events if k == "done"]
    assert done and done[0]["assistant_turn_idx"] == 2


@pytest.mark.asyncio
async def test_run_text_opening_rejects_when_voice_active(fake_session, mock_supabase):
    client, _ = mock_supabase
    fake_session["active_modality"] = "voice"
    with patch("app.services.intake.text_runner.aload_session", new=AsyncMock(return_value=fake_session)):
        with pytest.raises(ModalityConflictError):
            await _collect(run_text_opening(
                supabase_client=client, llm=MagicMock(),
                model="x", session_id="sess-1",
            ))


@pytest.mark.asyncio
async def test_run_text_turn_streams_text_and_writes_turns(fake_session, mock_supabase):
    """Happy path with no tool calls — streams text, writes both turns, fires coverage."""
    client, _ = mock_supabase

    async def fake_stream(**kwargs):
        yield ("text", "Hello ")
        yield ("text", "there.")
        yield ("done", {"text": "Hello there.", "stop_reason": "stop"})

    mock_append = AsyncMock(side_effect=[
        {"idx": 0, "role": "user", "content": "hi", "modality": "text"},
        {"idx": 1, "role": "assistant", "content": "Hello there.", "modality": "text"},
    ])

    with patch("app.services.intake.text_runner.aload_session", new=AsyncMock(return_value=fake_session)), \
         patch("app.services.intake.text_runner.append_turn_for_session", new=mock_append), \
         patch("app.services.intake.text_runner.stream_llm_turn", new=fake_stream), \
         patch("app.services.intake.text_runner.build_dynamic_prompt", return_value="SYS"), \
         patch("app.services.intake.text_runner.coverage_tracker_run", new=AsyncMock()) as mock_cov:
        events = await _collect(run_text_turn(
            supabase_client=client, llm=MagicMock(),
            model="claude-sonnet-4-6", session_id="sess-1", user_message="hi",
        ))

    text_events = [p for k, p in events if k == "text"]
    assert text_events == ["Hello ", "there."]
    assert mock_append.call_count == 2
    mock_cov.assert_called_once()

    done_events = [p for k, p in events if k == "done"]
    assert len(done_events) == 1
    # OpenAI vocabulary now: stream_turn passes the provider's
    # finish_reason through untouched. The frontend never compares
    # this value (verified by grep), so the wire change is safe.
    assert done_events[0]["stop_reason"] == "stop"
    assert done_events[0]["text"] == "Hello there."


@pytest.mark.asyncio
async def test_run_text_turn_coverage_failure_is_logged_and_does_not_crash(fake_session, mock_supabase):
    """The fire-and-forget coverage task is supervised: when the coverage coroutine
    RAISES, the done-callback logs the exception (and the caller turn still finishes
    cleanly). A bare asyncio.create_task would swallow this silently."""
    client, _ = mock_supabase

    async def fake_stream(**kwargs):
        yield ("text", "Hi.")
        yield ("done", {"text": "Hi.", "stop_reason": "stop"})

    mock_append = AsyncMock(side_effect=[
        {"idx": 0, "role": "user", "content": "hi", "modality": "text"},
        {"idx": 1, "role": "assistant", "content": "Hi.", "modality": "text"},
    ])

    async def boom(**kwargs):
        raise RuntimeError("coverage exploded")

    with patch("app.services.intake.text_runner.aload_session", new=AsyncMock(return_value=fake_session)), \
         patch("app.services.intake.text_runner.append_turn_for_session", new=mock_append), \
         patch("app.services.intake.text_runner.stream_llm_turn", new=fake_stream), \
         patch("app.services.intake.text_runner.build_dynamic_prompt", return_value="SYS"), \
         patch("app.services.intake.text_runner.coverage_tracker_run", new=boom), \
         patch("app.services.intake.text_runner.logger") as mock_logger:
        events = await _collect(run_text_turn(
            supabase_client=client, llm=MagicMock(),
            model="x", session_id="sess-1", user_message="hi",
        ))
        # Let the background coverage task run + its done-callback fire.
        for _ in range(5):
            await asyncio.sleep(0)

    # Caller turn completed normally despite the background failure.
    done_events = [p for k, p in events if k == "done"]
    assert len(done_events) == 1
    # OpenAI vocabulary now: stream_turn passes the provider's
    # finish_reason through untouched. The frontend never compares
    # this value (verified by grep), so the wire change is safe.
    assert done_events[0]["stop_reason"] == "stop"

    # The supervision callback logged the background failure.
    assert mock_logger.error.called or mock_logger.warning.called
    logged_events = [
        c.args[0] for c in (mock_logger.error.call_args_list + mock_logger.warning.call_args_list)
        if c.args
    ]
    assert any("coverage" in str(ev).lower() for ev in logged_events)


@pytest.mark.asyncio
async def test_run_text_turn_coverage_task_tracked_then_released(fake_session, mock_supabase):
    """The coverage task is retained in the module-level tracking set (so CPython
    cannot GC-cancel a pending task), then the done-callback removes it once done."""
    client, _ = mock_supabase

    async def fake_stream(**kwargs):
        yield ("done", {"text": "", "stop_reason": "stop"})

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_coverage(**kwargs):
        started.set()
        await release.wait()

    text_runner._coverage_tasks.clear()

    with patch("app.services.intake.text_runner.aload_session", new=AsyncMock(return_value=fake_session)), \
         patch("app.services.intake.text_runner.append_turn_for_session", new=AsyncMock(return_value={"idx": 0})), \
         patch("app.services.intake.text_runner.stream_llm_turn", new=fake_stream), \
         patch("app.services.intake.text_runner.build_dynamic_prompt", return_value="SYS"), \
         patch("app.services.intake.text_runner.coverage_tracker_run", new=slow_coverage):
        await _collect(run_text_turn(
            supabase_client=client, llm=MagicMock(),
            model="x", session_id="sess-1", user_message="hi",
        ))

        # Coverage task is in-flight and held by the tracking set (not GC-eligible).
        await started.wait()
        assert len(text_runner._coverage_tasks) == 1

        # Let it finish; the done-callback must remove it from the set.
        release.set()
        for _ in range(5):
            await asyncio.sleep(0)

    assert len(text_runner._coverage_tasks) == 0


@pytest.mark.asyncio
async def test_run_text_turn_tool_use_loop(fake_session, mock_supabase):
    """Tool-use turn: loop iterates, tool handler called, second LLM call generates
    follow-up text. Final assistant turn contains combined text."""
    client, _ = mock_supabase

    call_count = 0

    async def fake_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: text + tool_use
            yield ("text", "Got it. ")
            yield ("tool_call", {
                "id": "toolu_1", "name": "update_answer",
                "input": {"qid": "q4_must_haves", "text": "Python", "confidence": "high"},
            })
            yield ("done", {"text": "Got it. ", "stop_reason": "tool_calls"})
        else:
            # Second call: follow-up text after tool_result
            yield ("text", "Any other must-haves?")
            yield ("done", {"text": "Any other must-haves?", "stop_reason": "stop"})

    mock_append = AsyncMock(side_effect=[
        {"idx": 0, "role": "user", "content": "Python", "modality": "text"},
        {"idx": 1, "role": "assistant", "content": "Got it. Any other must-haves?",
         "modality": "text",
         "tool_calls": [{"name": "update_answer", "args": {"qid": "q4_must_haves", "text": "Python"}}]},
    ])
    mock_tool = AsyncMock(return_value={"ok": True})

    with patch("app.services.intake.text_runner.aload_session", new=AsyncMock(return_value=fake_session)), \
         patch("app.services.intake.text_runner.append_turn_for_session", new=mock_append), \
         patch("app.services.intake.text_runner.stream_llm_turn", new=fake_stream), \
         patch("app.services.intake.text_runner.build_dynamic_prompt", return_value="SYS"), \
         patch("app.services.intake.text_runner.ahandle_tool_call", new=mock_tool), \
         patch("app.services.intake.text_runner.coverage_tracker_run", new=AsyncMock()):
        events = await _collect(run_text_turn(
            supabase_client=client, llm=MagicMock(),
            model="x", session_id="sess-1", user_message="Python",
        ))

    # stream_llm_turn was called twice (once for tool_use, once for follow-up)
    assert call_count == 2

    # Tool handler was called exactly once
    mock_tool.assert_awaited_once()
    tc_kwarg = mock_tool.call_args.kwargs["tool_call"]
    assert tc_kwarg["name"] == "update_answer"
    assert tc_kwarg["id"] == "toolu_1"

    # User sees text from BOTH iterations
    text_events = [p for k, p in events if k == "text"]
    assert text_events == ["Got it. ", "Any other must-haves?"]

    # tool_call event was yielded
    tool_events = [p for k, p in events if k == "tool_call"]
    assert len(tool_events) == 1
    assert tool_events[0]["name"] == "update_answer"

    # Done event has combined text and terminal stop_reason
    done_events = [p for k, p in events if k == "done"]
    assert len(done_events) == 1
    # OpenAI vocabulary now: stream_turn passes the provider's
    # finish_reason through untouched. The frontend never compares
    # this value (verified by grep), so the wire change is safe.
    assert done_events[0]["stop_reason"] == "stop"
    assert done_events[0]["text"] == "Got it. Any other must-haves?"

    # assistant turn persisted with combined text
    assistant_call = mock_append.call_args_list[1]
    assert assistant_call.kwargs["content"] == "Got it. Any other must-haves?"
    assert assistant_call.kwargs["tool_calls"][0]["name"] == "update_answer"


@pytest.mark.asyncio
async def test_run_text_turn_executes_tool_calls(fake_session, mock_supabase):
    """Original tool execution test: tool handler is called with correct args."""
    client, _ = mock_supabase

    call_count = 0

    async def fake_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield ("text", "Got it. ")
            yield ("tool_call", {
                "id": "toolu_1", "name": "update_answer",
                "input": {"qid": "q4_must_haves", "text": "Python", "confidence": "high"},
            })
            yield ("done", {"text": "Got it. ", "stop_reason": "tool_calls"})
        else:
            yield ("done", {"text": "", "stop_reason": "stop"})

    mock_append = AsyncMock(side_effect=[
        {"idx": 0, "role": "user", "content": "Python", "modality": "text"},
        {"idx": 1, "role": "assistant", "content": "Got it. ", "modality": "text",
         "tool_calls": [{"name": "update_answer", "args": {"qid": "q4_must_haves", "text": "Python"}}]},
    ])
    mock_tool = AsyncMock(return_value={"ok": True})

    with patch("app.services.intake.text_runner.aload_session", new=AsyncMock(return_value=fake_session)), \
         patch("app.services.intake.text_runner.append_turn_for_session", new=mock_append), \
         patch("app.services.intake.text_runner.stream_llm_turn", new=fake_stream), \
         patch("app.services.intake.text_runner.build_dynamic_prompt", return_value="SYS"), \
         patch("app.services.intake.text_runner.ahandle_tool_call", new=mock_tool), \
         patch("app.services.intake.text_runner.coverage_tracker_run", new=AsyncMock()):
        events = await _collect(run_text_turn(
            supabase_client=client, llm=MagicMock(),
            model="x", session_id="sess-1", user_message="Python",
        ))

    mock_tool.assert_awaited_once()
    args = mock_tool.call_args
    assert args.kwargs["session_id"] == "sess-1"
    assert args.kwargs["tool_call"]["name"] == "update_answer"

    assistant_append = mock_append.call_args_list[1]
    assert assistant_append.kwargs["role"] == "assistant"
    assert assistant_append.kwargs["tool_calls"][0]["name"] == "update_answer"


@pytest.mark.asyncio
async def test_run_text_turn_sets_modality_lock(fake_session, mock_supabase):
    client, chain = mock_supabase

    async def fake_stream(**kwargs):
        yield ("done", {"text": "", "stop_reason": "stop"})

    with patch("app.services.intake.text_runner.aload_session", new=AsyncMock(return_value=fake_session)), \
         patch("app.services.intake.text_runner.append_turn_for_session", new=AsyncMock(return_value={"idx": 0})), \
         patch("app.services.intake.text_runner.stream_llm_turn", new=fake_stream), \
         patch("app.services.intake.text_runner.build_dynamic_prompt", return_value="SYS"), \
         patch("app.services.intake.text_runner.coverage_tracker_run", new=AsyncMock()):
        await _collect(run_text_turn(
            supabase_client=client, llm=MagicMock(),
            model="x", session_id="sess-1", user_message="hi",
        ))

    update_calls = [c for c in chain.update.call_args_list]
    assert any(c.args[0].get("active_modality") == "text" for c in update_calls)
    assert any(c.args[0].get("status") == "active" for c in update_calls)


@pytest.mark.asyncio
async def test_run_text_turn_tool_use_loop_guard(fake_session, mock_supabase):
    """Infinite tool_use loop guard: stops after _MAX_TOOL_ITERATIONS, logs warning."""
    client, _ = mock_supabase

    call_count = 0

    async def fake_stream_always_tool(**kwargs):
        nonlocal call_count
        call_count += 1
        yield ("tool_call", {
            "id": f"toolu_{call_count}", "name": "update_answer",
            "input": {"qid": "q1", "text": f"iter{call_count}", "confidence": "high"},
        })
        yield ("done", {"text": "", "stop_reason": "tool_calls"})

    mock_append = AsyncMock(side_effect=[
        {"idx": 0, "role": "user", "content": "test", "modality": "text"},
        {"idx": 1, "role": "assistant", "content": "", "modality": "text"},
    ])
    mock_tool = AsyncMock(return_value={"ok": True})

    with patch("app.services.intake.text_runner.aload_session", new=AsyncMock(return_value=fake_session)), \
         patch("app.services.intake.text_runner.append_turn_for_session", new=mock_append), \
         patch("app.services.intake.text_runner.stream_llm_turn", new=fake_stream_always_tool), \
         patch("app.services.intake.text_runner.build_dynamic_prompt", return_value="SYS"), \
         patch("app.services.intake.text_runner.ahandle_tool_call", new=mock_tool), \
         patch("app.services.intake.text_runner.coverage_tracker_run", new=AsyncMock()), \
         patch("app.services.intake.text_runner.logger") as mock_logger:
        events = await _collect(run_text_turn(
            supabase_client=client, llm=MagicMock(),
            model="x", session_id="sess-1", user_message="test",
        ))

    # Loop must not exceed _MAX_TOOL_ITERATIONS
    assert call_count == _MAX_TOOL_ITERATIONS
    # Guard warning was logged
    mock_logger.warning.assert_called_with(
        "tool_use_loop_guard_hit",
        session_id="sess-1",
        iterations=_MAX_TOOL_ITERATIONS,
        # Kept in the log even though it no longer drives control flow — it is
        # the only remaining record of what the provider actually said.
        stop_reason="tool_calls",
    )
    # Function still terminates with a done event
    done_events = [p for k, p in events if k == "done"]
    assert len(done_events) == 1


@pytest.mark.asyncio
async def test_run_text_turn_tool_messages_appended_correctly(fake_session, mock_supabase):
    """Verify the messages list is built in OpenAI shape: the assistant turn
    carries a sibling tool_calls array, and one role:"tool" message per call is
    appended before the second gateway call."""
    client, _ = mock_supabase

    captured_messages: list[list] = []
    call_count = 0

    async def fake_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        # Capture messages passed to each call
        captured_messages.append(list(kwargs.get("messages", [])))
        if call_count == 1:
            yield ("tool_call", {
                "id": "toolu_abc", "name": "mark_status",
                "input": {"qid": "q4_must_haves", "status": "complete"},
            })
            yield ("done", {"text": "", "stop_reason": "tool_calls"})
        else:
            yield ("text", "All done!")
            yield ("done", {"text": "All done!", "stop_reason": "stop"})

    mock_append = AsyncMock(side_effect=[
        {"idx": 0, "role": "user", "content": "done", "modality": "text"},
        {"idx": 1, "role": "assistant", "content": "All done!", "modality": "text"},
    ])
    mock_tool = AsyncMock(return_value={"ok": True})

    with patch("app.services.intake.text_runner.aload_session", new=AsyncMock(return_value=fake_session)), \
         patch("app.services.intake.text_runner.append_turn_for_session", new=mock_append), \
         patch("app.services.intake.text_runner.stream_llm_turn", new=fake_stream), \
         patch("app.services.intake.text_runner.build_dynamic_prompt", return_value="SYS"), \
         patch("app.services.intake.text_runner.ahandle_tool_call", new=mock_tool), \
         patch("app.services.intake.text_runner.coverage_tracker_run", new=AsyncMock()):
        await _collect(run_text_turn(
            supabase_client=client, llm=MagicMock(),
            model="x", session_id="sess-1", user_message="done",
        ))

    assert call_count == 2

    # Second call's messages end with the OPENAI shape:
    # [..., {"role": "assistant", "tool_calls": [{"id", "type", "function"}]},
    #       {"role": "tool", "tool_call_id": ..., "content": ...}]
    # It was Anthropic content blocks — a tool_use block inside an assistant
    # content array answered by a user turn of tool_result blocks — which
    # OpenAI's Chat Completions schema cannot accept at all.
    import json as _json

    msgs_second_call = captured_messages[1]
    second_to_last = msgs_second_call[-2]
    last = msgs_second_call[-1]

    assert second_to_last["role"] == "assistant"
    calls = second_to_last["tool_calls"]
    assert [c["id"] for c in calls] == ["toolu_abc"]
    assert calls[0]["type"] == "function"
    assert calls[0]["function"]["name"] == "mark_status"
    # arguments is a JSON STRING, not the decoded dict the event carried.
    assert isinstance(calls[0]["function"]["arguments"], str)
    assert _json.loads(calls[0]["function"]["arguments"])["qid"] == "q4_must_haves"

    assert last["role"] == "tool"
    assert last["tool_call_id"] == "toolu_abc"
    assert isinstance(last["content"], str)
