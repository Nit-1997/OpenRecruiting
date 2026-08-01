from pipecat.frames.frames import (
    Frame,
    UserStartedSpeakingFrame,
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from src.logging_config import get_logger

logger = get_logger(__name__)


class InterruptContextCleaner(FrameProcessor):
    def __init__(self, messages: list[dict], **kwargs):
        super().__init__(**kwargs)
        self._messages = messages
        self._bot_speaking = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
        elif isinstance(frame, UserStartedSpeakingFrame) and self._bot_speaking:
            self._annotate_last_assistant_message()

        await self.push_frame(frame, direction)

    def _annotate_last_assistant_message(self):
        for i in range(len(self._messages) - 1, -1, -1):
            msg = self._messages[i]
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if content and not content.endswith("..."):
                    msg["content"] = content + "..."
                    logger.info("Truncated interrupted assistant message")
                break
