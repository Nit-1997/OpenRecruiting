"""TranscriptAccumulatorProcessor — the end-of-call transcript must survive
pipecat's in-place context-summarization compaction.

Incident (candidate_round b94111e1, 2026-06-12): a full screening interview was
misread as 36 chars of candidate content because end-of-call counting ran over
the compacted `messages` list, so the session errored and the transcript was
discarded. The accumulator is the append-only record the end-of-call paths read
instead.
"""

import asyncio

from pipecat.frames.frames import LLMContextFrame
from pipecat.processors.frame_processor import FrameDirection

from src.pipeline.transcript_accumulator import TranscriptAccumulatorProcessor


class _Ctx:
    def __init__(self, messages):
        self._messages = messages

    def get_messages(self):
        return self._messages


def _drive(proc, messages):
    frame = LLMContextFrame(context=_Ctx(messages))
    asyncio.run(proc.process_frame(frame, FrameDirection.DOWNSTREAM))


def test_turns_survive_summarization_compaction():
    proc = TranscriptAccumulatorProcessor()
    messages = [
        {"role": "system", "content": "interviewer prompt"},
        {"role": "assistant", "content": "Hi! Tell me about your LLM project."},
        {"role": "user", "content": "I built a medical record summarization system at CVS Health."},
        {"role": "assistant", "content": "How did you evaluate it?"},
        {"role": "user", "content": "Golden datasets, adversarial cases, LLM-as-judge with clinical rubrics."},
    ]
    _drive(proc, messages)

    # The summarizer compacts the SAME list in place: prior turns -> one summary.
    messages[:] = [
        {"role": "system", "content": "interviewer prompt"},
        {"role": "assistant", "content": "Conversation summary: candidate built a med-records summarizer."},
        {"role": "user", "content": "I think I'm done. Thank you so much."},
    ]
    _drive(proc, messages)

    user_text = " ".join(t["content"] for t in proc.turns if t["role"] == "user")
    assert "CVS Health" in user_text
    assert "LLM-as-judge" in user_text
    assert "I think I'm done. Thank you so much." in user_text
    assert not any(
        t["content"].lower().startswith("conversation summary") for t in proc.turns
    )


def test_turn_order_is_first_appearance():
    proc = TranscriptAccumulatorProcessor()
    messages = [
        {"role": "assistant", "content": "Q1?"},
        {"role": "user", "content": "A1"},
    ]
    _drive(proc, messages)
    messages.extend([
        {"role": "assistant", "content": "Q2?"},
        {"role": "user", "content": "A2"},
    ])
    _drive(proc, messages)

    assert [t["content"] for t in proc.turns] == ["Q1?", "A1", "Q2?", "A2"]


def test_no_duplicates_on_repeated_sync():
    proc = TranscriptAccumulatorProcessor()
    messages = [
        {"role": "assistant", "content": "Hello there."},
        {"role": "user", "content": "Hi."},
    ]
    _drive(proc, messages)
    _drive(proc, messages)

    assert len(proc.turns) == 2


def test_tool_blocks_skipped_text_blocks_kept():
    proc = TranscriptAccumulatorProcessor()
    messages = [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "One last thing on this."},
                {"type": "tool_use", "id": "t1", "name": "mark_question_covered", "input": {}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": '{"ok": true}'},
                {"type": "text", "text": "I think I'm done. Thank you so much."},
            ],
        },
    ]
    _drive(proc, messages)

    assert proc.turns == [
        {"role": "assistant", "content": "One last thing on this."},
        {"role": "user", "content": "I think I'm done. Thank you so much."},
    ]


def test_bind_messages_fallback_when_frame_has_no_context():
    proc = TranscriptAccumulatorProcessor()
    messages = [{"role": "user", "content": "captured via the bound list"}]
    proc.bind_messages(messages)

    frame = LLMContextFrame(context=None)
    asyncio.run(proc.process_frame(frame, FrameDirection.DOWNSTREAM))

    assert proc.turns == [{"role": "user", "content": "captured via the bound list"}]


def test_sync_swallows_malformed_messages():
    proc = TranscriptAccumulatorProcessor()
    messages = [
        {"role": "user", "content": 42},
        {"content": "no role"},
        {"role": "assistant"},
        {"role": "user", "content": "   "},
        {"role": "user", "content": "real turn"},
    ]
    _drive(proc, messages)

    assert proc.turns == [{"role": "user", "content": "real turn"}]
