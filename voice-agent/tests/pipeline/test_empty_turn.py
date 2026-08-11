"""EmptyTurnDetector — the guard for the turn that produced nothing.

READ THIS BEFORE TRUSTING THIS FILE. conftest.py stubs pipecat into
sys.modules, so every frame class here is a local stub, not pipecat's. These
tests prove the detector's LOGIC — which frame combinations it flags, and that
it forwards everything unchanged. They prove nothing about whether pipecat
emits those frames in that order. That was verified separately, by reading
pipecat 0.0.102 inside the built image; the line numbers are recorded in
src/pipeline/empty_turn.py's docstring.
"""

import logging

import pytest

from pipecat.frames.frames import (
    FunctionCallsStartedFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    StartInterruptionFrame,
    TextFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from src.pipeline.empty_turn import EmptyTurnDetector


DOWN = FrameDirection.DOWNSTREAM


@pytest.fixture
def detector():
    det = EmptyTurnDetector(model="voice-intake")
    det.pushed = []

    async def _capture(frame, direction=DOWN):
        det.pushed.append(frame)

    det.push_frame = _capture
    return det


async def _run(detector, *frames):
    for frame in frames:
        await detector.process_frame(frame, DOWN)


def _warnings(caplog):
    return [r for r in caplog.records if getattr(r, "event", None) == "llm_empty_turn"]


@pytest.mark.asyncio
async def test_a_turn_with_text_is_not_flagged(detector, caplog):
    with caplog.at_level(logging.WARNING):
        await _run(
            detector,
            LLMFullResponseStartFrame(),
            LLMTextFrame("Got it, a Staff Backend Engineer."),
            LLMFullResponseEndFrame(),
        )
    assert _warnings(caplog) == []


@pytest.mark.asyncio
async def test_a_turn_with_a_surviving_tool_call_is_not_flagged(detector, caplog):
    """A tool call that survived pipecat's `if function_name and arguments`
    guard reaches run_function_calls, which broadcasts this frame. Its presence
    is the proof the call was not dropped."""
    with caplog.at_level(logging.WARNING):
        await _run(
            detector,
            LLMFullResponseStartFrame(),
            FunctionCallsStartedFrame(function_calls=[object()]),
            LLMFullResponseEndFrame(),
        )
    assert _warnings(caplog) == []


@pytest.mark.asyncio
async def test_a_turn_with_neither_is_flagged_by_name(detector, caplog):
    """The regression phase 7 introduced: OpenAILLMService drops a tool call
    whose accumulated arguments are empty, so no handler runs and no frame is
    broadcast. Without this detector the turn is completely silent."""
    with caplog.at_level(logging.WARNING):
        await _run(detector, LLMFullResponseStartFrame(), LLMFullResponseEndFrame())

    records = _warnings(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].model == "voice-intake"
    assert records[0].turn_index == 1


@pytest.mark.asyncio
async def test_whitespace_only_text_is_still_an_empty_turn(detector, caplog):
    """A blank LLMTextFrame produces no speech. Counting it as text would make
    the detector claim a turn was fine when the recruiter heard nothing."""
    with caplog.at_level(logging.WARNING):
        await _run(
            detector,
            LLMFullResponseStartFrame(),
            LLMTextFrame("   \n"),
            LLMFullResponseEndFrame(),
        )
    assert len(_warnings(caplog)) == 1


@pytest.mark.parametrize("interruption_cls", [InterruptionFrame, StartInterruptionFrame])
@pytest.mark.asyncio
async def test_an_interrupted_turn_is_not_flagged(detector, caplog, interruption_cls):
    """A barge-in legitimately ends a turn before it produces anything. Flagging
    it would bury the real signal under noise on every interruption.

    Both classes are covered because pipecat 0.0.102 deprecates
    StartInterruptionFrame in favour of its InterruptionFrame base but still
    emits the subclass; the detector keys on the base so either one suppresses.
    """
    with caplog.at_level(logging.WARNING):
        await _run(
            detector,
            LLMFullResponseStartFrame(),
            interruption_cls(),
            LLMFullResponseEndFrame(),
        )
    assert _warnings(caplog) == []


@pytest.mark.asyncio
async def test_a_tool_call_arriving_before_the_start_frame_is_not_flagged(detector, caplog):
    """FunctionCallsStartedFrame is a SystemFrame and LLMFullResponseStartFrame
    is a ControlFrame, so pipecat's priority queue can deliver the tool call
    FIRST even though it was pushed second (frame_processor.py:1043, :91-118) —
    pipecat's own run_test harness reproduces this exact order.

    If the detector cleared its tool-call flag on the start frame, this turn
    would be reported as 'the answer was NOT recorded' on a turn where the call
    in fact succeeded. That is the guard inverting its own meaning, so it is
    pinned here rather than left to the ordering holding by luck.
    """
    with caplog.at_level(logging.WARNING):
        await _run(
            detector,
            FunctionCallsStartedFrame(function_calls=[object()]),
            LLMFullResponseStartFrame(),
            LLMFullResponseEndFrame(),
        )
    assert _warnings(caplog) == []


@pytest.mark.asyncio
async def test_an_early_tool_call_is_consumed_by_one_turn_only(detector, caplog):
    """The pending flag must clear at the end of the turn that used it —
    otherwise one tool call early in a session would silence the detector for
    every turn after it."""
    with caplog.at_level(logging.WARNING):
        await _run(
            detector,
            FunctionCallsStartedFrame(function_calls=[object()]),
            LLMFullResponseStartFrame(),
            LLMFullResponseEndFrame(),
            LLMFullResponseStartFrame(),
            LLMFullResponseEndFrame(),
        )

    records = _warnings(caplog)
    assert len(records) == 1
    assert records[0].turn_index == 2


@pytest.mark.asyncio
async def test_state_resets_so_a_later_empty_turn_is_still_caught(detector, caplog):
    """State that leaks between turns would let one good turn mask every empty
    turn after it — the failure mode that makes a detector worse than none."""
    with caplog.at_level(logging.WARNING):
        await _run(
            detector,
            LLMFullResponseStartFrame(),
            LLMTextFrame("Hello."),
            LLMFullResponseEndFrame(),
            LLMFullResponseStartFrame(),
            LLMFullResponseEndFrame(),
        )

    records = _warnings(caplog)
    assert len(records) == 1
    assert records[0].turn_index == 2


@pytest.mark.asyncio
async def test_every_frame_is_forwarded_unchanged(detector, caplog):
    """The detector is observational. A guard that swallows frames would break
    TTS — every frame it sees is on the path to the recruiter's speakers."""
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("part one "),
        TextFrame("unrelated"),
        FunctionCallsStartedFrame(function_calls=[object()]),
        LLMFullResponseEndFrame(),
    ]
    with caplog.at_level(logging.WARNING):
        await _run(detector, *frames)

    assert detector.pushed == frames
