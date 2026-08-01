import asyncio
import random
import time

from pipecat.frames.frames import (
    Frame,
    TTSSpeakFrame,
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    LLMFullResponseStartFrame,
    LLMFullResponseEndFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

FILLER_PHRASES = [
    "Hmm, let me think about that...",
    "One moment...",
    "Got it, let me process that...",
    "Mm-hmm...",
    "Right...",
]


class FillerProcessor(FrameProcessor):
    def __init__(
        self,
        delay_secs: float = 3.0,
        bot_cooldown_secs: float = 5.0,
        min_speech_secs: float = 0.5,
        end_event: asyncio.Event | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._delay_secs = delay_secs
        self._bot_cooldown_secs = bot_cooldown_secs
        self._min_speech_secs = min_speech_secs
        self._end_event = end_event
        self._bot_speaking = False
        self._bot_stop_time: float = 0.0
        self._llm_responding = False
        self._user_speech_start: float = 0.0
        self._user_turn_active = False
        self._filler_task: asyncio.Task | None = None

    def _in_bot_cooldown(self) -> bool:
        if self._bot_speaking or self._llm_responding:
            return True
        return (time.monotonic() - self._bot_stop_time) < self._bot_cooldown_secs

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
            self._user_turn_active = False
            self._cancel_filler_timer()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            self._bot_stop_time = time.monotonic()
            self._user_turn_active = False
        elif isinstance(frame, LLMFullResponseStartFrame):
            self._llm_responding = True
            self._user_turn_active = False
            self._cancel_filler_timer()
        elif isinstance(frame, LLMFullResponseEndFrame):
            self._llm_responding = False
        elif isinstance(frame, UserStartedSpeakingFrame):
            self._cancel_filler_timer()
            if not self._in_bot_cooldown():
                self._user_speech_start = time.monotonic()
                self._user_turn_active = True
        elif isinstance(frame, UserStoppedSpeakingFrame):
            if self._user_turn_active and not self._in_bot_cooldown():
                speech_duration = time.monotonic() - self._user_speech_start
                if speech_duration >= self._min_speech_secs:
                    self._start_filler_timer()
                else:
                    self._user_turn_active = False

        await self.push_frame(frame, direction)

    def _start_filler_timer(self):
        if self._end_event and self._end_event.is_set():
            return
        self._cancel_filler_timer()
        self._filler_task = asyncio.create_task(self._speak_filler())

    def _cancel_filler_timer(self):
        if self._filler_task and not self._filler_task.done():
            self._filler_task.cancel()
            self._filler_task = None

    async def _speak_filler(self):
        await asyncio.sleep(self._delay_secs)
        if self._end_event and self._end_event.is_set():
            return
        if self._user_turn_active and not self._in_bot_cooldown():
            filler = random.choice(FILLER_PHRASES)
            await self.push_frame(
                TTSSpeakFrame(text=filler, append_to_context=False)
            )
            self._user_turn_active = False
