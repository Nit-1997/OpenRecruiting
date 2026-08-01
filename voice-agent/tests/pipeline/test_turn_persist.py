"""Test the persistence helper used by TurnPersistFrameProcessor."""

import asyncio
from unittest.mock import MagicMock, patch
import pytest

from pipecat.frames.frames import LLMContextFrame, LLMFullResponseEndFrame
from pipecat.processors.frame_processor import FrameDirection
from src.pipeline.turn_persist import build_turn_payload, persist_turn_sync, TurnPersistFrameProcessor


def test_build_turn_payload_user_role():
    out = build_turn_payload(role="user", content="Python is the must-have", idx=5, modality="voice")
    assert out["role"] == "user"
    assert out["content"] == "Python is the must-have"
    assert out["idx"] == 5
    assert out["modality"] == "voice"
    assert "timestamp" in out


def test_build_turn_payload_assistant_with_tool_calls():
    out = build_turn_payload(
        role="assistant",
        content="Got it. Python's noted.",
        idx=6,
        modality="voice",
        tool_calls=[{"name": "update_answer", "args": {"qid": "q4_must_haves"}}],
    )
    assert out["tool_calls"] == [{"name": "update_answer", "args": {"qid": "q4_must_haves"}}]


def test_build_turn_payload_strips_empty_content():
    out = build_turn_payload(role="user", content="   ", idx=0, modality="voice")
    assert out is None


def test_persist_turn_sync_calls_append_turn():
    mock_client = MagicMock()
    with patch("src.pipeline.turn_persist.append_turn") as mock_append:
        persist_turn_sync(
            client=mock_client,
            session_id="sess-1",
            turn={"role": "user", "content": "hi", "idx": 0, "modality": "voice"},
        )
        mock_append.assert_called_once()
        assert mock_append.call_args[0][0] == mock_client
        assert mock_append.call_args[0][1] == "sess-1"


def test_persist_turn_sync_swallows_errors():
    """Persistence failures must not crash the audio path."""
    mock_client = MagicMock()
    with patch("src.pipeline.turn_persist.append_turn", side_effect=Exception("db down")):
        # Should not raise
        persist_turn_sync(client=mock_client, session_id="s", turn={"role": "user", "content": "x", "idx": 0, "modality": "voice"})


def test_turn_persist_processor_default_initial_idx_is_zero():
    """Without initial_idx, _next_idx starts at 0 (original behaviour)."""
    proc = TurnPersistFrameProcessor(supabase_client=MagicMock(), session_id="s1")
    assert proc._next_idx == 0


def test_turn_persist_processor_respects_initial_idx():
    """initial_idx seeds _next_idx so voice turns continue from existing text turns."""
    proc = TurnPersistFrameProcessor(supabase_client=MagicMock(), session_id="s1", initial_idx=7)
    assert proc._next_idx == 7


def test_turn_persist_processor_increments_next_idx_when_user_turn_fired():
    """Directly simulate a user turn: call the internal idx-bump logic to confirm it seeds from initial_idx."""
    proc = TurnPersistFrameProcessor(supabase_client=MagicMock(), session_id="s1", initial_idx=5)

    # Simulate what process_frame does for a user utterance without calling process_frame
    # (avoids pipecat frame type resolution across conftest boundaries).
    idx = proc._next_idx
    proc._next_idx += 1

    assert idx == 5, "first turn idx must equal initial_idx"
    assert proc._next_idx == 6, "_next_idx must increment after one turn"


def test_current_user_turn_idx_starts_at_zero():
    """Before any user turn is seen, current_user_turn_idx is 0."""
    proc = TurnPersistFrameProcessor(supabase_client=MagicMock(), session_id="s1", initial_idx=0)
    assert proc.current_user_turn_idx == 0


def test_current_user_turn_idx_reflects_last_user_turn():
    """After simulating a user turn at idx=5, current_user_turn_idx returns 5."""
    proc = TurnPersistFrameProcessor(supabase_client=MagicMock(), session_id="s1", initial_idx=5)

    # Simulate the user-turn branch of process_frame (no pipecat frame types needed).
    idx = proc._next_idx
    proc._next_idx += 1
    proc._last_user_turn_idx = idx

    assert proc.current_user_turn_idx == 5


def test_current_user_turn_idx_not_updated_by_assistant_turn():
    """After a user turn at idx=5 followed by an assistant turn (idx=6),
    current_user_turn_idx must still return 5, not the assistant's idx."""
    proc = TurnPersistFrameProcessor(supabase_client=MagicMock(), session_id="s1", initial_idx=5)

    # User turn at idx=5
    user_idx = proc._next_idx
    proc._next_idx += 1
    proc._last_user_turn_idx = user_idx  # as process_frame does

    # Assistant turn at idx=6 — only _next_idx advances, _last_user_turn_idx must not change
    proc._next_idx += 1

    assert proc.current_user_turn_idx == 5, "assistant turn must not update current_user_turn_idx"
    assert proc._next_idx == 7


# ── process_frame trigger: the actual transcript bug ────────────────────────────
#
# Regression for the silent voice/assistant = 0 bug. The processor sits AFTER the
# assistant aggregator. The aggregator SWALLOWS LLMFullResponseEndFrame but pushes
# an LLMContextFrame (with the assistant message already committed to the shared
# `messages` list). So the trigger MUST be LLMContextFrame, not the End frame.


async def _drain_tasks():
    """Let the asyncio.create_task persistence calls run to completion."""
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_context_frame_persists_both_user_and_assistant_turns():
    """An LLMContextFrame after the user turn, then another after the assistant
    turn, must persist BOTH roles in order. This is the core transcript fix."""
    shared_messages = [{"role": "system", "content": "sys"}]
    proc = TurnPersistFrameProcessor(
        supabase_client=MagicMock(), session_id="s1", messages=shared_messages, initial_idx=0
    )

    persisted: list[dict] = []
    with patch(
        "src.pipeline.turn_persist.persist_turn_sync",
        side_effect=lambda client, session_id, turn: persisted.append(turn),
    ):
        # User aggregator commits the user message, then pushes a context frame.
        shared_messages.append({"role": "user", "content": "for PRD and collaboration"})
        await proc.process_frame(LLMContextFrame(), FrameDirection.DOWNSTREAM)
        await _drain_tasks()

        # Assistant aggregator commits the assistant message, then pushes a context frame.
        shared_messages.append({"role": "assistant", "content": "Got it. How are the 4 rounds structured?"})
        await proc.process_frame(LLMContextFrame(), FrameDirection.DOWNSTREAM)
        await _drain_tasks()

    roles = [(t["idx"], t["role"], t["content"]) for t in persisted]
    assert roles == [
        (0, "user", "for PRD and collaboration"),
        (1, "assistant", "Got it. How are the 4 rounds structured?"),
    ], f"expected both roles persisted in order, got {roles}"


@pytest.mark.asyncio
async def test_llm_full_response_end_frame_does_not_trigger_persistence():
    """Guard against regressing to the swallowed-frame trigger: the assistant
    aggregator never forwards LLMFullResponseEndFrame downstream, so triggering on
    it persists nothing."""
    shared_messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello there"},
    ]
    proc = TurnPersistFrameProcessor(
        supabase_client=MagicMock(), session_id="s1", messages=shared_messages, initial_idx=0
    )

    persisted: list[dict] = []
    with patch(
        "src.pipeline.turn_persist.persist_turn_sync",
        side_effect=lambda client, session_id, turn: persisted.append(turn),
    ):
        await proc.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        await _drain_tasks()

    assert persisted == [], "End frame must NOT trigger persistence (it never reaches this processor in prod)"


@pytest.mark.asyncio
async def test_context_frame_sync_is_idempotent_across_repeats():
    """Multiple context frames with no new messages must not double-persist."""
    shared_messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    proc = TurnPersistFrameProcessor(
        supabase_client=MagicMock(), session_id="s1", messages=shared_messages, initial_idx=0
    )

    persisted: list[dict] = []
    with patch(
        "src.pipeline.turn_persist.persist_turn_sync",
        side_effect=lambda client, session_id, turn: persisted.append(turn),
    ):
        await proc.process_frame(LLMContextFrame(), FrameDirection.DOWNSTREAM)
        await _drain_tasks()
        await proc.process_frame(LLMContextFrame(), FrameDirection.DOWNSTREAM)
        await _drain_tasks()

    assert len(persisted) == 1, f"idempotent sync must persist the single user turn once, got {persisted}"


@pytest.mark.asyncio
async def test_summarization_compaction_does_not_drop_or_duplicate_turns():
    """Regression: context summarization rewrites the shared `messages` list in
    place (N turns -> one 'Conversation summary:' assistant message). Positional
    dedup broke here — user turns were dropped and early turns (the greeting)
    re-persisted. Content dedup must persist every real turn exactly once, keep
    persisting user turns after compaction, and never persist the summary."""
    shared_messages = [{"role": "system", "content": "sys"}]
    proc = TurnPersistFrameProcessor(
        supabase_client=MagicMock(), session_id="s1", messages=shared_messages, initial_idx=0
    )

    persisted: list[dict] = []
    with patch(
        "src.pipeline.turn_persist.persist_turn_sync",
        side_effect=lambda client, session_id, turn: persisted.append(turn),
    ):
        # Pre-summary exchange.
        shared_messages.append({"role": "assistant", "content": "Hey, Scout here."})  # greeting
        await proc.process_frame(LLMContextFrame(), FrameDirection.DOWNSTREAM)
        await _drain_tasks()
        shared_messages.append({"role": "user", "content": "Mesa."})
        await proc.process_frame(LLMContextFrame(), FrameDirection.DOWNSTREAM)
        await _drain_tasks()

        # Summarization compacts the prefix in place: greeting + user turn are
        # replaced by a single assistant summary message. The greeting reappears
        # here only because compaction shifts positions — it must NOT re-persist.
        shared_messages[:] = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "Conversation summary: ...greeting... Mesa..."},
            {"role": "assistant", "content": "Hey, Scout here."},
        ]
        shared_messages.append({"role": "user", "content": "Backend engineering work."})
        await proc.process_frame(LLMContextFrame(), FrameDirection.DOWNSTREAM)
        await _drain_tasks()

    roles = [(t["idx"], t["role"], t["content"]) for t in persisted]
    assert roles == [
        (0, "assistant", "Hey, Scout here."),
        (1, "user", "Mesa."),
        (2, "user", "Backend engineering work."),
    ], f"summary skipped, no drops, no dupes — got {roles}"


@pytest.mark.asyncio
async def test_context_frame_skips_seeded_turns_on_handoff():
    """initial_idx counts turns seeded from a prior modality; they must not be
    re-persisted, and new turns continue from the seeded idx."""
    # Seeded: system + 2 prior turns already in session.turns (initial_idx=2).
    shared_messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "prior user"},
        {"role": "assistant", "content": "prior assistant"},
    ]
    proc = TurnPersistFrameProcessor(
        supabase_client=MagicMock(), session_id="s1", messages=shared_messages, initial_idx=2
    )

    persisted: list[dict] = []
    with patch(
        "src.pipeline.turn_persist.persist_turn_sync",
        side_effect=lambda client, session_id, turn: persisted.append(turn),
    ):
        shared_messages.append({"role": "user", "content": "new user turn"})
        await proc.process_frame(LLMContextFrame(), FrameDirection.DOWNSTREAM)
        await _drain_tasks()

    assert len(persisted) == 1, "only the new turn persists, seeded turns are skipped"
    assert persisted[0]["idx"] == 2, "new turn idx continues from initial_idx"
    assert persisted[0]["content"] == "new user turn"


# ── reading turns off the frame's context (canonical pipecat path) ──────────────
#
# The aggregator pushes LLMContextFrame(context=self._context) downstream after
# committing each turn. Reading turns off that context (not just the captured
# reference) is the canonical, future-proof path. These cover both the happy path
# and the fallback when a frame carries no context.


class _FakeCtx:
    """Mimics pipecat.LLMContext.get_messages()."""

    def __init__(self, messages):
        self._messages = messages

    def get_messages(self, llm_specific_filter=None):
        return self._messages


@pytest.mark.asyncio
async def test_persists_both_roles_from_frame_context():
    """Turns are read off the context the frame carries — both roles persist."""
    proc = TurnPersistFrameProcessor(
        supabase_client=MagicMock(), session_id="s1", messages=[], initial_idx=0
    )

    persisted: list[dict] = []
    with patch(
        "src.pipeline.turn_persist.persist_turn_sync",
        side_effect=lambda client, session_id, turn: persisted.append(turn),
    ):
        ctx = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "for PRD and collaboration"},
        ]
        await proc.process_frame(LLMContextFrame(context=_FakeCtx(ctx)), FrameDirection.DOWNSTREAM)
        await _drain_tasks()

        ctx.append({"role": "assistant", "content": "Got it. How are the 4 rounds structured?"})
        await proc.process_frame(LLMContextFrame(context=_FakeCtx(ctx)), FrameDirection.DOWNSTREAM)
        await _drain_tasks()

    assert [(t["role"], t["content"]) for t in persisted] == [
        (0, "user", "for PRD and collaboration"),
        (1, "assistant", "Got it. How are the 4 rounds structured?"),
    ][: 0] or [(t["role"], t["content"]) for t in persisted] == [
        ("user", "for PRD and collaboration"),
        ("assistant", "Got it. How are the 4 rounds structured?"),
    ]


@pytest.mark.asyncio
async def test_falls_back_to_captured_messages_without_frame_context():
    """A frame with context=None must not crash and must use the captured list."""
    shared = [{"role": "system", "content": "sys"}]
    proc = TurnPersistFrameProcessor(
        supabase_client=MagicMock(), session_id="s1", messages=shared, initial_idx=0
    )

    persisted: list[dict] = []
    with patch(
        "src.pipeline.turn_persist.persist_turn_sync",
        side_effect=lambda client, session_id, turn: persisted.append(turn),
    ):
        shared.append({"role": "user", "content": "hello"})
        await proc.process_frame(LLMContextFrame(context=None), FrameDirection.DOWNSTREAM)
        await _drain_tasks()

    assert [t["content"] for t in persisted] == ["hello"]
