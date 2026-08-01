import time

from src.logging_config import get_logger
from pipecat.frames.frames import (
    Frame,
    TTSStartedFrame,
    TTSStoppedFrame,
    LLMFullResponseStartFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = get_logger(__name__)


class MetricsLogger(FrameProcessor):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._user_stop_time: float = 0.0
        self._llm_start_time: float = 0.0
        self._tts_start_time: float = 0.0
        self._turn_active = False
        self._turn_count: int = 0
        self._bot_speaking: bool = False
        self._bot_speaking_start: float = 0.0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        now = time.monotonic()

        if isinstance(frame, UserStoppedSpeakingFrame):
            self._user_stop_time = now
            self._turn_active = True
            self._turn_count += 1

        elif isinstance(frame, LLMFullResponseStartFrame) and self._turn_active:
            self._llm_start_time = now

        elif isinstance(frame, TTSStartedFrame) and self._turn_active:
            self._tts_start_time = now

        elif isinstance(frame, TTSStoppedFrame) and self._turn_active:
            self._log_turn_metrics(was_interrupted=False)
            self._reset()

        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
            self._bot_speaking_start = now

        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False

        elif isinstance(frame, UserStartedSpeakingFrame):
            if self._bot_speaking:
                bot_speaking_duration_ms = int((now - self._bot_speaking_start) * 1000) if self._bot_speaking_start else 0
                logger.info("voice_barge_in", extra={
                    "event": "voice_barge_in",
                    "bot_speaking_duration_ms": bot_speaking_duration_ms,
                })
            if self._turn_active:
                self._log_turn_metrics(was_interrupted=True)
                self._reset()

        await self.push_frame(frame, direction)

    def _log_turn_metrics(self, was_interrupted: bool = False):
        if self._user_stop_time == 0.0:
            return
        to_llm_ms = int((self._llm_start_time - self._user_stop_time) * 1000) if self._llm_start_time else 0
        llm_to_tts_ms = int((self._tts_start_time - self._llm_start_time) * 1000) if self._tts_start_time and self._llm_start_time else 0
        total_ms = int((self._tts_start_time - self._user_stop_time) * 1000) if self._tts_start_time else 0
        logger.info("voice_turn_metrics", extra={
            "event": "voice_turn_metrics",
            "silence_to_llm_ms": to_llm_ms,
            "llm_to_tts_ms": llm_to_tts_ms,
            "total_rtl_ms": total_ms,
            "turn_number": self._turn_count,
            "was_interrupted": was_interrupted,
        })

    def _reset(self):
        self._turn_active = False
        self._user_stop_time = 0.0
        self._llm_start_time = 0.0
        self._tts_start_time = 0.0
