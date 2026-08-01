"""Stub the heavy WebRTC/pipecat/anthropic deps so `src.main` imports on hosts
without aiortc + the pipecat runtime installed.

The screening offer-route test only exercises the FastAPI route's token-validation
branch (403 before any WebRTC handling), so a MagicMock surface for everything
pipecat/aiortc/anthropic touch at IMPORT time is sufficient. Mirrors the per-test
pipecat stubbing already used by tests/pipeline/conftest.py and
tests/intake/conftest.py.
"""

import sys
from unittest.mock import MagicMock

_HEAVY_MODULES = [
    "aiortc",
    "anthropic",
    "pipecat",
    "pipecat.frames",
    "pipecat.frames.frames",
    "pipecat.pipeline",
    "pipecat.pipeline.runner",
    "pipecat.pipeline.task",
    "pipecat.pipeline.pipeline",
    "pipecat.processors",
    "pipecat.processors.frame_processor",
    "pipecat.processors.frameworks",
    "pipecat.processors.frameworks.rtvi",
    "pipecat.processors.aggregators",
    "pipecat.processors.aggregators.llm_context",
    "pipecat.processors.aggregators.llm_response_universal",
    "pipecat.utils",
    "pipecat.utils.context",
    "pipecat.utils.context.llm_context_summarization",
    "pipecat.turns",
    "pipecat.turns.user_turn_strategies",
    "pipecat.adapters",
    "pipecat.adapters.schemas",
    "pipecat.adapters.schemas.tools_schema",
    "pipecat.adapters.schemas.function_schema",
    "pipecat.services",
    "pipecat.services.llm_service",
    "pipecat.services.deepgram",
    "pipecat.services.deepgram.flux",
    "pipecat.services.deepgram.flux.stt",
    "pipecat.services.deepgram.tts",
    "pipecat.services.anthropic",
    "pipecat.services.anthropic.llm",
    "pipecat.transports",
    "pipecat.transports.base_transport",
    "pipecat.transports.smallwebrtc",
    "pipecat.transports.smallwebrtc.transport",
    "pipecat.transports.smallwebrtc.request_handler",
]

for _name in _HEAVY_MODULES:
    sys.modules.setdefault(_name, MagicMock())
