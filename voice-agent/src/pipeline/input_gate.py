import asyncio

from src.logging_config import get_logger

logger = get_logger(__name__)
from pipecat.frames.frames import (
    Frame,
    TranscriptionFrame,
    InterimTranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

_BLOCKED_FRAMES = (
    TranscriptionFrame,
    InterimTranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)


class PostEndInputGate(FrameProcessor):
    """Sits between STT and user aggregator. Once end_event is set,
    swallows all user speech frames so the LLM is never triggered again."""

    def __init__(self, end_event: asyncio.Event, **kwargs):
        super().__init__(**kwargs)
        self._end_event = end_event
        self._logged_gate = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if self._end_event.is_set() and isinstance(frame, _BLOCKED_FRAMES):
            if not self._logged_gate:
                logger.info("PostEndInputGate: blocking post-goodbye user frames")
                self._logged_gate = True
            return

        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)
