"""Regression for candidate_round b94111e1 (2026-06-12).

A ~7-minute screening triggered context summarization; the end-of-call path
counted candidate content over the COMPACTED `messages` list, saw only the
post-summary tail ("I think I'm done. Thank you so much." = 36 chars
< MIN_INTERVIEWER_CHARS), errored the session, and discarded the transcript —
no feedback, no Lambda. Counting/formatting must run over the accumulator's
append-only turns instead.

Lives under tests/screening/ so this directory's conftest stubs the heavy
WebRTC/pipecat deps and `src.main` imports on the host.
"""

from src import main
from src.pipeline.transcript_accumulator import TranscriptAccumulatorProcessor

_FULL_INTERVIEW = [
    {"role": "system", "content": "screening prompt"},
    {"role": "assistant", "content": "Hi! Tell me about a time you integrated an LLM into a real product."},
    {
        "role": "user",
        "content": (
            "I built a medical health record summarization system at CVS Health "
            "using Med Gemma and LangGraph for workflow orchestration."
        ),
    },
    {"role": "assistant", "content": "How did you evaluate and test the AI behavior?"},
    {
        "role": "user",
        "content": (
            "We built a golden dataset with adversarial cases and an LLM-as-judge "
            "rubric aligned with the clinical team, plus regression runs before deploys."
        ),
    },
]

# What the live context looked like at disconnect — the summarizer had already
# compacted the real turns into a single synthetic assistant message.
_COMPACTED_TAIL = [
    {"role": "system", "content": "screening prompt"},
    {"role": "assistant", "content": "Conversation summary: candidate discussed an LLM project at CVS Health."},
    {"role": "user", "content": "I think I'm done. Thank you so much."},
]


def _accumulate_through_compaction() -> TranscriptAccumulatorProcessor:
    proc = TranscriptAccumulatorProcessor()
    proc.bind_messages(list(_FULL_INTERVIEW))
    proc._sync()
    proc.bind_messages(list(_COMPACTED_TAIL))
    proc._sync()
    return proc


def test_compacted_context_reproduces_the_incident():
    # The old read path: counting over the compacted live context misclassifies
    # a full interview as below the minimum-content threshold.
    assert main.count_interviewer_chars(_COMPACTED_TAIL) < main.MIN_INTERVIEWER_CHARS


def test_candidate_chars_counted_from_accumulator_pass_threshold():
    proc = _accumulate_through_compaction()
    turns = proc.turns or _COMPACTED_TAIL
    assert main.count_interviewer_chars(turns) >= main.MIN_INTERVIEWER_CHARS


def test_format_screening_transcript_keeps_presummary_turns():
    proc = _accumulate_through_compaction()
    transcript = main.format_screening_transcript(proc.turns)

    assert f"{main.SCREENING_CANDIDATE_SPEAKER}: I built a medical health record" in transcript
    assert "LLM-as-judge" in transcript
    assert f"{main.SCREENING_CANDIDATE_SPEAKER}: I think I'm done. Thank you so much." in transcript
    assert "Conversation summary" not in transcript
