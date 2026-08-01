import asyncio

from src.logging_config import get_logger

logger = get_logger(__name__)
from pipecat.frames.frames import (
    Frame,
    TextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

END_MARKER = "[END]"
PARTIAL_PREFIXES = {"[", "[E", "[EN", "[END"}

GOODBYE_PATTERNS = [
    "have a great day",
    "have a great rest of your day",
    "thanks for your time",
    "thank you for your time",
    "that's all i need",
    "i have everything i need",
    "thanks so much for taking the time",
    "thanks for sharing your feedback",
    "have a wonderful day",
    "bye bye",
]

GOODBYE_FALLBACK_DELAY = 2.0


class EndOfConversationDetector(FrameProcessor):
    def __init__(self, end_event: asyncio.Event, **kwargs):
        super().__init__(**kwargs)
        self._end_event = end_event
        self._detected_in_response = False
        self._buffer = ""
        self._full_response_text = ""
        self._goodbye_fallback_task: asyncio.Task | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            self._buffer = ""
            self._full_response_text = ""
            self._detected_in_response = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TextFrame) and frame.text:
            self._buffer += frame.text
            self._full_response_text += frame.text

            if END_MARKER in self._buffer:
                cleaned = self._buffer.replace(END_MARKER, "")
                self._detected_in_response = True
                self._buffer = ""
                if cleaned:
                    await self.push_frame(TextFrame(text=cleaned), direction)
                return

            held = ""
            for i in range(min(len(self._buffer), len(END_MARKER) - 1), 0, -1):
                tail = self._buffer[-i:]
                if tail in PARTIAL_PREFIXES:
                    held = tail
                    break

            if held:
                safe = self._buffer[:-len(held)]
                self._buffer = held
                if safe:
                    await self.push_frame(TextFrame(text=safe), direction)
            else:
                text = self._buffer
                self._buffer = ""
                await self.push_frame(TextFrame(text=text), direction)
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            if self._buffer:
                cleaned = self._buffer.replace(END_MARKER, "")
                if END_MARKER in self._buffer:
                    self._detected_in_response = True
                if cleaned:
                    await self.push_frame(TextFrame(text=cleaned), direction)
                self._buffer = ""

            if self._detected_in_response:
                logger.info("voice_conversation_end", extra={"event": "voice_conversation_end", "method": "end_marker"})
                self._detected_in_response = False
                self._cancel_goodbye_fallback()
                self._end_event.set()
            elif self._has_goodbye_pattern(self._full_response_text):
                logger.info("voice_conversation_end", extra={"event": "voice_conversation_end", "method": "goodbye_pattern"})
                self._start_goodbye_fallback()

            self._full_response_text = ""
            await self.push_frame(frame, direction)
            return

        await self.push_frame(frame, direction)

    def _has_goodbye_pattern(self, text: str) -> bool:
        lower = text.lower()
        return any(pattern in lower for pattern in GOODBYE_PATTERNS)

    def _start_goodbye_fallback(self):
        self._cancel_goodbye_fallback()
        self._goodbye_fallback_task = asyncio.create_task(self._goodbye_fallback_wait())

    def _cancel_goodbye_fallback(self):
        if self._goodbye_fallback_task and not self._goodbye_fallback_task.done():
            self._goodbye_fallback_task.cancel()
            self._goodbye_fallback_task = None

    async def _goodbye_fallback_wait(self):
        await asyncio.sleep(GOODBYE_FALLBACK_DELAY)
        if not self._end_event.is_set():
            logger.info("voice_conversation_end", extra={"event": "voice_conversation_end", "method": "goodbye_fallback"})
            self._end_event.set()
