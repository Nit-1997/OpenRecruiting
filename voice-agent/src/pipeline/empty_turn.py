"""EmptyTurnDetector — name the LLM turn that produced neither speech nor a tool call.

An LLM turn that produced no speech and no tool call is invisible from every
other vantage point in this service. /health stays green; the transcript simply
has no row; the recruiter hears silence and assumes they were not understood.

Two distinct causes land here, and both matter:

* the model returned nothing at all;
* a tool call was DROPPED. `OpenAILLMService` only dispatches tool calls if the
  LAST one's accumulated argument string is truthy — `if function_name and
  arguments:` at pipecat 0.0.102 `services/openai/base_llm.py:464` guards the
  `run_function_calls` at `:485`. A truncated `update_answer` therefore
  disappears before any handler runs: no dispatch, no result callback, no
  `FunctionCallsStartedFrame`, no error, no log. Worse, because the append and
  the dispatch live inside the SAME branch, an empty final call also discards
  every tool call already accumulated in that turn (`:437-439`) — the blast
  radius is the turn, not the one call.

  The service this replaced coerced the same case to `{}` and dispatched it
  (`services/anthropic/llm.py:474`), which surfaced as a visible
  `{"ok": false}` the model could see and retry against. That difference is a
  regression the gateway migration introduced, and it is why this processor
  exists.

A third cause shares the shape: malformed (rather than empty) arguments raise
inside `json.loads` at `base_llm.py:475`, outside any per-call try, and are
caught at `:525` as a generic completion error — again losing every tool call
in the turn.

This does not repair any of them. It converts them from silence into one named
log line (`llm_empty_turn`) that a session review can grep for. Repairing the
dropped call means overriding pipecat's `_process_context`, which is a fork of
~100 lines of its internals and would rot on the next pipecat bump; that is
deliberately not done here.

Why these two frames are the right signal, verified in the built image:

* `FunctionCallsStartedFrame` is broadcast ONLY when at least one call survived
  — `run_function_calls` returns early on an empty list (`llm_service.py:626`)
  before broadcasting at `:631`. And `broadcast_frame` pushes DOWNSTREAM first
  (`frame_processor.py:790`), so a processor placed after the LLM service sees
  it.
* `LLMFullResponseEndFrame` is pushed from a `finally` (`base_llm.py:526-528`),
  so the check fires even when the turn ended in an exception or a timeout.

Interrupted turns are excluded on purpose. A barge-in legitimately ends a turn
before it produces anything; flagging those would bury the real signal under
one line per interruption.

⚠️ FRAME ORDER IS NOT GUARANTEED, and this processor is built around that.
`FunctionCallsStartedFrame` and `StartInterruptionFrame` are **SystemFrame**s;
`LLMFullResponseStartFrame`/`EndFrame` are **ControlFrame**s. A FrameProcessor
handles system frames IMMEDIATELY (`frame_processor.py:1043`) but queues
everything else, on a priority queue that documents itself as ensuring "system
frames are processed before any other frames" (`:91-118`). So a tool-call frame
pushed AFTER the start frame can still arrive BEFORE it. Verified: pipecat's own
`run_test` harness delivers exactly that reordering.

The consequence, if this processor cleared its tool-call flag on the start
frame, would be a warning saying the recruiter's answer was NOT recorded on
turns where the tool call in fact succeeded — the guard inverting its own
meaning on the one path it exists to protect. Instead both system-frame flags
are PENDING flags: set whenever seen, cleared only at the end of a turn, never
by a start frame. System frames can only arrive early, never late, so this is
correct in the ordinary case and errs toward staying quiet in the rare one. A
missed warning is a far cheaper error here than a false one — this line's only
value is that it can be trusted.
"""

from pipecat.frames.frames import (
    Frame,
    FunctionCallsStartedFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from src.logging_config import get_logger

logger = get_logger(__name__)


class EmptyTurnDetector(FrameProcessor):
    """Observational. Forwards every frame unchanged; only ever logs.

    Place it immediately after the LLM service in the pipeline — downstream of
    the frames it watches, upstream of the TTS path it must not disturb.
    """

    def __init__(self, model: str = "", **kwargs):
        super().__init__(**kwargs)
        self._model = model
        self._turn_index = 0
        self._in_turn = False
        self._saw_text = False
        # Pending flags — set by SYSTEM frames, which can jump ahead of the
        # control frames that bracket a turn. Deliberately NOT reset on a start
        # frame; see the module docstring.
        self._tool_call_pending = False
        self._interruption_pending = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            self._turn_index += 1
            self._in_turn = True
            self._saw_text = False

        elif isinstance(frame, LLMTextFrame):
            # Blank text produces no speech, so it is not evidence of a turn
            # that reached the recruiter.
            if frame.text and frame.text.strip():
                self._saw_text = True

        elif isinstance(frame, FunctionCallsStartedFrame):
            self._tool_call_pending = True

        elif isinstance(frame, InterruptionFrame):
            self._interruption_pending = True

        elif isinstance(frame, LLMFullResponseEndFrame):
            produced_something = (
                self._saw_text or self._tool_call_pending or self._interruption_pending
            )
            if self._in_turn and not produced_something:
                logger.warning("llm_empty_turn", extra={
                    "event": "llm_empty_turn",
                    "model": self._model,
                    "turn_index": self._turn_index,
                    "detail": (
                        "LLM turn produced no speech and no surviving tool call. "
                        "Either the model returned nothing, or a tool call was "
                        "dropped for empty/malformed arguments before any handler "
                        "ran (pipecat openai/base_llm.py:464). The answer the "
                        "recruiter gave was NOT recorded."
                    ),
                })
            self._in_turn = False
            self._tool_call_pending = False
            self._interruption_pending = False

        await self.push_frame(frame, direction)
