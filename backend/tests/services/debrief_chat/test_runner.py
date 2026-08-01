"""Tests for DebriefChatRunner — the bounded Anthropic read-tool / propose loop.

The Anthropic boundary is the same `stream_llm_turn` seam the intake text runner
uses; we patch it on the runner module and script a fake event iterator. The repo
and read_tools are AsyncMocks. Covers: text-only, read-tool round-trip, propose_*
interception (turn ends, no tool_result fed back), iteration bound, fail-soft.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.debrief_chat.contracts import ChatEvent
from app.services.debrief_chat.runner import DebriefChatRunner

ORG_ID = "00000000-0000-0000-0000-000000000010"
PACKET_ID = "00000000-0000-0000-0000-0000000000f1"
CAND_A = "00000000-0000-0000-0000-0000000000a1"


def _packet():
    return {
        "role_title": "PM",
        "candidates": [{"candidate_id": CAND_A, "name": "Ada"}],
    }


def _repo(*, load=None):
    """Faithful conversation-repo double backed by a shared in-memory list.

    `append_turn` commits the turn (stamping an incrementing `idx`) so that the
    very next `load_turns` reflects it — exactly like the real repo. This is what
    surfaces the duplicate-current-user-message bug: the appended user turn is
    already present in the reloaded history.
    """
    store: list[dict] = list(load or [])
    repo = MagicMock()
    repo.store = store

    async def _append(packet_id, turn):
        stored = {**turn, "idx": len(store)}
        store.append(stored)
        return stored

    async def _load(packet_id):
        return list(store)

    repo.append_turn = AsyncMock(side_effect=_append)
    repo.load_turns = AsyncMock(side_effect=_load)
    return repo


def _read_tools(dispatch_return=None):
    rt = MagicMock()
    rt.dispatch = AsyncMock(return_value=dispatch_return or {"ok": True})
    return rt


def _runner(*, repo, read_tools, max_iters=4):
    return DebriefChatRunner(
        client=MagicMock(),
        model="claude-sonnet-4-6",
        max_iters=max_iters,
        max_tokens=1024,
        packet_body=_packet(),
        repo=repo,
        read_tools=read_tools,
        system_prompt="SYSTEM",
        packet_id=PACKET_ID,
    )


async def _collect(gen):
    return [ev async for ev in gen]


# ---------------------------------------------------------------------------
# Text-only turn
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_text_only_streams_tokens_and_persists_turns():
    repo = _repo()
    runner = _runner(repo=repo, read_tools=_read_tools())

    async def fake_stream(**kwargs):
        yield ("text", "Ada ")
        yield ("text", "edges Bob.")
        yield ("done", {"text": "Ada edges Bob.", "stop_reason": "end_turn"})

    with patch("app.services.debrief_chat.runner.stream_llm_turn", new=fake_stream):
        events = await _collect(runner.run("why does Ada win?"))

    tokens = [e.data for e in events if e.type == "token"]
    assert tokens == ["Ada ", "edges Bob."]
    done = [e for e in events if e.type == "done"]
    assert len(done) == 1 and "turn_idx" in done[0].data
    assert not [e for e in events if e.type in ("error", "proposed_action")]

    # User turn appended first, assistant turn second (text persisted, no action).
    assert repo.append_turn.await_count == 2
    user_turn = repo.append_turn.await_args_list[0].args[1]
    assert user_turn["role"] == "user" and user_turn["text"] == "why does Ada win?"
    assistant_turn = repo.append_turn.await_args_list[1].args[1]
    assert assistant_turn["role"] == "assistant"
    assert assistant_turn["text"] == "Ada edges Bob."
    assert assistant_turn["proposed_action"] is None


# ---------------------------------------------------------------------------
# Read-tool round-trip
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_read_tool_call_dispatches_and_loop_continues():
    repo = _repo()
    read_tools = _read_tools({"candidate_id": CAND_A, "rounds": []})
    runner = _runner(repo=repo, read_tools=read_tools)

    call_count = 0

    async def fake_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield ("text", "Let me check. ")
            yield (
                "tool_call",
                {"id": "t1", "name": "get_candidate_detail", "input": {"candidate_id": CAND_A}},
            )
            yield ("done", {"text": "Let me check. ", "stop_reason": "tool_use"})
        else:
            yield ("text", "Ada's round-2 rating is strong.")
            yield ("done", {"text": "Ada's round-2 rating is strong.", "stop_reason": "end_turn"})

    with patch("app.services.debrief_chat.runner.stream_llm_turn", new=fake_stream):
        events = await _collect(runner.run("where did Ada's score come from?"))

    # The read tool ran exactly once, with the model's args.
    read_tools.dispatch.assert_awaited_once_with(
        "get_candidate_detail", {"candidate_id": CAND_A}
    )
    assert call_count == 2  # loop continued after the tool_result
    tokens = [e.data for e in events if e.type == "token"]
    assert tokens == ["Let me check. ", "Ada's round-2 rating is strong."]
    done = [e for e in events if e.type == "done"]
    assert len(done) == 1
    assistant_turn = repo.append_turn.await_args_list[1].args[1]
    assert assistant_turn["text"] == "Let me check. Ada's round-2 rating is strong."


# ---------------------------------------------------------------------------
# propose_* interception
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_propose_tool_emits_action_and_breaks_without_tool_result():
    repo = _repo()
    read_tools = _read_tools()
    runner = _runner(repo=repo, read_tools=read_tools)

    call_count = 0

    async def fake_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        yield ("text", "I'd add a round. ")
        yield (
            "tool_call",
            {
                "id": "p1",
                "name": "propose_add_round",
                "input": {"candidate_ids": [CAND_A], "params": {"name": "Final"}},
            },
        )
        yield ("done", {"text": "I'd add a round. ", "stop_reason": "tool_use"})

    with patch("app.services.debrief_chat.runner.stream_llm_turn", new=fake_stream):
        events = await _collect(runner.run("should we add a final round for Ada?"))

    # The propose tool is NOT dispatched (no execution) and NO second model call.
    read_tools.dispatch.assert_not_awaited()
    assert call_count == 1

    proposed = [e for e in events if e.type == "proposed_action"]
    assert len(proposed) == 1
    assert proposed[0].data["kind"] == "propose_add_round"
    assert proposed[0].data["input"]["candidate_ids"] == [CAND_A]

    done = [e for e in events if e.type == "done"]
    assert len(done) == 1

    # The assistant turn persists the proposed action.
    assistant_turn = repo.append_turn.await_args_list[1].args[1]
    assert assistant_turn["proposed_action"]["kind"] == "propose_add_round"


@pytest.mark.asyncio
async def test_propose_record_decision_intercepted_with_specs_registered():
    """With PROPOSE_TOOL_SPECS registered, a propose_record_decision call is still
    intercepted (the propose-name set covers all 5 action tools): the turn emits a
    proposed_action and breaks with no tool_result fed back."""
    repo = _repo()
    read_tools = _read_tools()
    runner = _runner(repo=repo, read_tools=read_tools)

    call_count = 0

    async def fake_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        yield (
            "tool_call",
            {
                "id": "p2",
                "name": "propose_record_decision",
                "input": {"candidate_ids": [CAND_A], "verdict": "hire"},
            },
        )
        yield ("done", {"text": "", "stop_reason": "tool_use"})

    with patch("app.services.debrief_chat.runner.stream_llm_turn", new=fake_stream):
        events = await _collect(runner.run("record a hire for Ada"))

    read_tools.dispatch.assert_not_awaited()
    assert call_count == 1
    proposed = [e for e in events if e.type == "proposed_action"]
    assert len(proposed) == 1
    assert proposed[0].data["kind"] == "propose_record_decision"


@pytest.mark.asyncio
async def test_runner_registers_read_and_propose_tools():
    """The model is offered READ + PROPOSE tools (so it can actually call them)."""
    repo = _repo()
    runner = _runner(repo=repo, read_tools=_read_tools())

    seen = {}

    async def fake_stream(**kwargs):
        seen["tools"] = kwargs.get("tools")
        yield ("text", "ok")
        yield ("done", {"text": "ok", "stop_reason": "end_turn"})

    with patch("app.services.debrief_chat.runner.stream_llm_turn", new=fake_stream):
        await _collect(runner.run("hi"))

    names = {t["name"] for t in seen["tools"]}
    assert "get_candidate_detail" in names
    assert "propose_record_decision" in names
    assert "propose_add_round" in names


# ---------------------------------------------------------------------------
# Iteration bound
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_iteration_bound_terminates_gracefully():
    repo = _repo()
    read_tools = _read_tools()
    runner = _runner(repo=repo, read_tools=read_tools, max_iters=3)

    call_count = 0

    async def always_tool(**kwargs):
        nonlocal call_count
        call_count += 1
        yield (
            "tool_call",
            {"id": f"t{call_count}", "name": "get_candidate_detail", "input": {"candidate_id": CAND_A}},
        )
        yield ("done", {"text": "", "stop_reason": "tool_use"})

    with patch("app.services.debrief_chat.runner.stream_llm_turn", new=always_tool):
        events = await _collect(runner.run("loop please"))

    assert call_count == 3  # never exceeds max_iters
    done = [e for e in events if e.type == "done"]
    assert len(done) == 1
    assert not [e for e in events if e.type == "error"]
    # Assistant turn still persisted (graceful close).
    assert repo.append_turn.await_count == 2


# ---------------------------------------------------------------------------
# Fail-soft
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_model_exception_emits_single_static_error_and_persists_turn():
    repo = _repo()
    read_tools = _read_tools()
    runner = _runner(repo=repo, read_tools=read_tools)

    async def boom(**kwargs):
        raise RuntimeError("anthropic 529 overloaded: secret detail")
        yield  # pragma: no cover — make this an async generator

    with patch("app.services.debrief_chat.runner.stream_llm_turn", new=boom):
        events = await _collect(runner.run("why?"))

    errors = [e for e in events if e.type == "error"]
    assert len(errors) == 1
    # Static message — never leaks str(e).
    assert "529" not in errors[0].data["message"]
    assert "secret detail" not in errors[0].data["message"]
    # A graceful assistant turn is still persisted (user + assistant = 2 appends).
    assert repo.append_turn.await_count == 2
    done = [e for e in events if e.type == "done"]
    assert len(done) == 1


@pytest.mark.asyncio
async def test_entry_repo_failure_emits_error_without_raising():
    """A DB failure on the entry append_turn must not propagate out of the async
    generator and drop the SSE connection: run yields a single static error event
    (and a done), consistent with the in-loop fail-soft."""
    repo = MagicMock()
    repo.append_turn = AsyncMock(side_effect=RuntimeError("supabase down: secret"))
    repo.load_turns = AsyncMock(return_value=[])
    read_tools = _read_tools()
    runner = _runner(repo=repo, read_tools=read_tools)

    async def never_called(**kwargs):  # pragma: no cover — model never reached
        yield ("text", "unreachable")

    with patch("app.services.debrief_chat.runner.stream_llm_turn", new=never_called):
        events = await _collect(runner.run("why?"))

    errors = [e for e in events if e.type == "error"]
    assert len(errors) == 1
    assert "secret" not in errors[0].data["message"]
    done = [e for e in events if e.type == "done"]
    assert len(done) == 1
    # The model was never reached; the failure was the entry repo write.
    read_tools.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_read_tool_dispatch_failure_does_not_crash_turn():
    """A failing read tool returns a structured error tool_result, not a crash."""
    repo = _repo()
    read_tools = _read_tools()
    read_tools.dispatch = AsyncMock(side_effect=RuntimeError("supabase down"))
    runner = _runner(repo=repo, read_tools=read_tools)

    call_count = 0

    async def fake_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield (
                "tool_call",
                {"id": "t1", "name": "get_candidate_detail", "input": {"candidate_id": CAND_A}},
            )
            yield ("done", {"text": "", "stop_reason": "tool_use"})
        else:
            yield ("text", "Sorry, I couldn't fetch that.")
            yield ("done", {"text": "Sorry, I couldn't fetch that.", "stop_reason": "end_turn"})

    with patch("app.services.debrief_chat.runner.stream_llm_turn", new=fake_stream):
        events = await _collect(runner.run("detail please"))

    # Loop continued (the tool error became a tool_result), turn finished cleanly.
    assert call_count == 2
    assert not [e for e in events if e.type == "error"]
    done = [e for e in events if e.type == "done"]
    assert len(done) == 1


@pytest.mark.asyncio
async def test_history_is_replayed_into_messages():
    """Reloaded turns ARE the messages array: prior turns + the current user turn,
    appended exactly once. The last entry must be a single current-user message and
    there must be no two consecutive identical user messages."""
    repo = _repo(
        load=[
            {"role": "user", "text": "first?", "idx": 0},
            {"role": "assistant", "text": "first answer", "idx": 1},
        ],
    )
    runner = _runner(repo=repo, read_tools=_read_tools())

    seen = {}

    async def fake_stream(**kwargs):
        seen["messages"] = kwargs.get("messages")
        yield ("text", "ok")
        yield ("done", {"text": "ok", "stop_reason": "end_turn"})

    with patch("app.services.debrief_chat.runner.stream_llm_turn", new=fake_stream):
        await _collect(runner.run("second?"))

    assert seen["messages"] == [
        {"role": "user", "content": "first?"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second?"},
    ]
    # The current user turn is the last message, exactly once.
    assert seen["messages"][-1] == {"role": "user", "content": "second?"}
    # No two consecutive identical messages (the duplicate-user-turn bug).
    msgs = seen["messages"]
    assert not any(msgs[i] == msgs[i + 1] for i in range(len(msgs) - 1))


@pytest.mark.asyncio
async def test_current_user_message_not_duplicated():
    """Regression: the current user message reaches the model exactly once.

    The faithful repo commits the user turn before history is reloaded, so a naive
    `reloaded_history + [current_user_message]` double-appends it. Count of the
    current message text across the messages array must be exactly 1.
    """
    repo = _repo(
        load=[
            {"role": "assistant", "text": "earlier answer", "idx": 0},
        ],
    )
    runner = _runner(repo=repo, read_tools=_read_tools())

    seen = {}

    async def fake_stream(**kwargs):
        seen["messages"] = kwargs.get("messages")
        yield ("text", "ok")
        yield ("done", {"text": "ok", "stop_reason": "end_turn"})

    current = "is Ada ahead of Bob?"
    with patch("app.services.debrief_chat.runner.stream_llm_turn", new=fake_stream):
        await _collect(runner.run(current))

    user_occurrences = [
        m
        for m in seen["messages"]
        if m.get("role") == "user" and m.get("content") == current
    ]
    assert len(user_occurrences) == 1
    assert seen["messages"][-1] == {"role": "user", "content": current}
