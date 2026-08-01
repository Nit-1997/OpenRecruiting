"""Tests for seeding OpenAILLMContext from an existing intake_sessions row."""

import pytest

from src.intake.context_seed import (
    build_seed_messages,
    build_continuation_primer,
    format_turn_for_context,
)


def test_format_turn_user():
    t = {
        "idx": 5, "role": "user", "content": "yeah we do four rounds",
        "modality": "voice", "timestamp": "2026-05-27T14:23:08Z",
    }
    msg = format_turn_for_context(t)
    assert msg == {"role": "user", "content": "yeah we do four rounds"}


def test_format_turn_assistant_strips_tool_calls():
    """Tool calls are recorded in `turns` for audit but should not be replayed
    into a resumed context — those side effects already happened against the DB."""
    t = {
        "idx": 6, "role": "assistant",
        "content": "Got it. I noted Python and PostgreSQL.",
        "modality": "voice",
        "tool_calls": [{"name": "update_answer", "args": {"qid": "q4_must_haves"}}],
    }
    msg = format_turn_for_context(t)
    assert msg == {"role": "assistant", "content": "Got it. I noted Python and PostgreSQL."}
    assert "tool_calls" not in msg


def test_build_seed_messages_empty_turns_returns_just_system():
    out = build_seed_messages(
        system_prompt="You are Scout.",
        turns=[],
        primer=None,
    )
    assert out == [{"role": "system", "content": "You are Scout."}]


def test_build_seed_messages_includes_turns_in_order():
    turns = [
        {"idx": 0, "role": "assistant", "content": "Hi, I'm Scout.", "modality": "voice"},
        {"idx": 1, "role": "user", "content": "Hi.", "modality": "voice"},
        {"idx": 2, "role": "assistant", "content": "What's the role?", "modality": "voice"},
    ]
    out = build_seed_messages(system_prompt="SYS", turns=turns, primer=None)
    assert out[0] == {"role": "system", "content": "SYS"}
    assert out[1]["content"] == "Hi, I'm Scout."
    assert out[3]["content"] == "What's the role?"


def test_build_seed_messages_preserves_turn_order_by_idx_not_input_order():
    """Turns from DB are usually idx-sorted, but defensive: re-sort by idx anyway."""
    turns = [
        {"idx": 2, "role": "assistant", "content": "third", "modality": "voice"},
        {"idx": 0, "role": "assistant", "content": "first", "modality": "voice"},
        {"idx": 1, "role": "user", "content": "second", "modality": "voice"},
    ]
    out = build_seed_messages(system_prompt="SYS", turns=turns, primer=None)
    assert [m["content"] for m in out[1:]] == ["first", "second", "third"]


def test_build_seed_messages_with_primer_appends_after_history():
    turns = [
        {"idx": 0, "role": "user", "content": "we do four rounds", "modality": "text"},
    ]
    out = build_seed_messages(
        system_prompt="SYS",
        turns=turns,
        primer="Picking up where we left off — you mentioned four rounds.",
    )
    # Last message must be an assistant primer that the user will hear/see first
    assert out[-1]["role"] == "assistant"
    assert "four rounds" in out[-1]["content"]


def test_build_continuation_primer_from_recent_user_turn():
    turns = [
        {"idx": 0, "role": "assistant", "content": "Hi.", "modality": "voice"},
        {"idx": 1, "role": "user", "content": "we do four rounds for senior BE", "modality": "voice"},
        {"idx": 2, "role": "assistant", "content": "Got it.", "modality": "voice"},
    ]
    primer = build_continuation_primer(turns)
    assert primer is not None
    # The primer should reference what the user just said, not the assistant's response.
    assert "four rounds" in primer.lower() or "senior" in primer.lower() or "where we left off" in primer.lower()


def test_build_continuation_primer_returns_none_when_no_history():
    assert build_continuation_primer([]) is None


def test_build_continuation_primer_truncates_long_user_quote():
    long_text = "this is a really really really long user turn " * 50
    turns = [{"idx": 0, "role": "user", "content": long_text, "modality": "text"}]
    primer = build_continuation_primer(turns)
    assert primer is not None
    assert len(primer) < 400  # primer should stay terse
