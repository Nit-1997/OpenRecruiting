"""Stub pipecat for pipeline unit tests that don't need the real Pipecat runtime."""

import sys
from unittest.mock import AsyncMock, MagicMock


# ── Frame stubs ───────────────────────────────────────────────────────────────

class Frame:
    pass


class TranscriptionFrame(Frame):
    def __init__(self, text="", user_id="", timestamp=""):
        self.text = text
        self.user_id = user_id
        self.timestamp = timestamp


class TextFrame(Frame):
    def __init__(self, text=""):
        self.text = text


class LLMFullResponseStartFrame(Frame):
    pass


class LLMFullResponseEndFrame(Frame):
    pass


class LLMRunFrame(Frame):
    pass


class LLMContextFrame(Frame):
    def __init__(self, context=None):
        self.context = context


class LLMTextFrame(Frame):
    def __init__(self, text=""):
        self.text = text


class FunctionCallsStartedFrame(Frame):
    """Broadcast by pipecat only when at least one tool call survived
    (services/llm_service.py:626-631 returns early on an empty list), which is
    what makes it the signal EmptyTurnDetector keys on."""

    def __init__(self, function_calls=()):
        self.function_calls = function_calls


class InterruptionFrame(Frame):
    pass


class StartInterruptionFrame(InterruptionFrame):
    pass


# ── FrameDirection stub ───────────────────────────────────────────────────────

class FrameDirection:
    DOWNSTREAM = "downstream"
    UPSTREAM = "upstream"


# ── FrameProcessor stub ───────────────────────────────────────────────────────

class FrameProcessor:
    async def process_frame(self, frame, direction):
        pass

    async def push_frame(self, frame, direction):
        pass


# ── Build sys.modules stubs ───────────────────────────────────────────────────

_frames_mod = MagicMock()
_frames_mod.Frame = Frame
_frames_mod.TranscriptionFrame = TranscriptionFrame
_frames_mod.TextFrame = TextFrame
_frames_mod.LLMFullResponseStartFrame = LLMFullResponseStartFrame
_frames_mod.LLMFullResponseEndFrame = LLMFullResponseEndFrame
_frames_mod.LLMRunFrame = LLMRunFrame
_frames_mod.LLMContextFrame = LLMContextFrame
_frames_mod.LLMTextFrame = LLMTextFrame
_frames_mod.FunctionCallsStartedFrame = FunctionCallsStartedFrame
_frames_mod.InterruptionFrame = InterruptionFrame
_frames_mod.StartInterruptionFrame = StartInterruptionFrame

_fp_mod = MagicMock()
_fp_mod.FrameProcessor = FrameProcessor
_fp_mod.FrameDirection = FrameDirection

_pipecat_frames = MagicMock()
_pipecat_frames.frames = _frames_mod

_pipecat_processors = MagicMock()
_pipecat_processors.frame_processor = _fp_mod

_pipecat = MagicMock()
_pipecat.frames = _pipecat_frames
_pipecat.processors = _pipecat_processors

# Force-register: override any stubs registered by tests/intake/conftest.py
# to ensure TranscriptionFrame and FrameProcessor are real types, not MagicMock instances.
sys.modules["pipecat"] = _pipecat
sys.modules["pipecat.frames"] = _pipecat_frames
sys.modules["pipecat.frames.frames"] = _frames_mod
sys.modules["pipecat.processors"] = _pipecat_processors
sys.modules["pipecat.processors.frame_processor"] = _fp_mod
