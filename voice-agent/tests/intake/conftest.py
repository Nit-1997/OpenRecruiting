"""Stub pipecat for unit tests that don't need the real Pipecat runtime."""

import sys
from unittest.mock import MagicMock


class EndFrame:
    """Stub for pipecat.frames.frames.EndFrame — used to verify drain sends the right frame."""


# Build a minimal pipecat stub so modules that import pipecat can be imported locally.
_frames_mod = MagicMock()
_frames_mod.EndFrame = EndFrame

_pipecat_frames = MagicMock()
_pipecat_frames.frames = _frames_mod

_pipecat = MagicMock()
_pipecat.frames = _pipecat_frames

sys.modules.setdefault("pipecat", _pipecat)
sys.modules.setdefault("pipecat.frames", _pipecat_frames)
sys.modules.setdefault("pipecat.frames.frames", _frames_mod)
