"""TranscriptAccumulatorProcessor — append-only, in-memory conversation record
that SURVIVES context summarization.

The screening + fallback-feedback end-of-call paths used to count candidate/
interviewer content and format the final transcript from the live LLMContext
`messages` list. pipecat's context summarizer COMPACTS that list in place
(N turns → one "Conversation summary:" assistant message), so any call long
enough to trigger summarization lost every pre-summary turn at end-of-call:
a full, legitimate interview was misclassified as
`insufficient_candidate_content` (only the post-summary tail was counted), the
backend marked the session error, and the transcript evidence was discarded
(candidate_round b94111e1, 2026-06-12).

Mechanics mirror TurnPersistFrameProcessor (same trigger frame, same dedup):
sync on every LLMContextFrame, dedup by (role, content) signature, skip the
summarizer's compacted-history message and non-text tool blocks. Turns
accumulate in `self.turns` as {role, content: str} and are never removed, so
end-of-call counting/formatting sees the WHOLE conversation regardless of how
many times the context was compacted mid-call.
"""

from __future__ import annotations

from typing import Any

import structlog

from pipecat.frames.frames import Frame, LLMContextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from src.pipeline.turn_persist import _SUMMARY_PREFIX, _text_of, _turn_key

logger = structlog.get_logger(__name__)


class TranscriptAccumulatorProcessor(FrameProcessor):
    """Place AFTER the assistant context aggregator (like TurnPersistFrameProcessor),
    so each LLMContextFrame arrives with the just-finished turn already committed."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.turns: list[dict[str, str]] = []
        self._seen: set[str] = set()
        self._messages: list[dict[str, Any]] = []

    def bind_messages(self, messages: list[dict[str, Any]]) -> None:
        """Fallback source when a frame carries no readable context (older
        pipecat builds / unit-test fakes). The factory binds the shared
        LLMContext list here at pipeline-build time."""
        self._messages = messages

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame):
            self._adopt_frame_messages(frame)
            self._sync()
        await self.push_frame(frame, direction)

    def _adopt_frame_messages(self, frame: Frame) -> None:
        ctx = getattr(frame, "context", None)
        getter = getattr(ctx, "get_messages", None)
        if not callable(getter):
            return
        try:
            msgs = getter()
        except Exception as e:
            logger.warning("transcript_accumulator_context_read_failed", error=str(e))
            return
        if isinstance(msgs, list):
            self._messages = msgs

    def _sync(self) -> None:
        try:
            for m in self._messages:
                role = m.get("role")
                if role not in ("user", "assistant"):
                    continue
                text = _text_of(m.get("content"))
                if not text:
                    continue
                if role == "assistant" and text.lower().startswith(_SUMMARY_PREFIX):
                    continue
                key = _turn_key(role, text)
                if key in self._seen:
                    continue
                self._seen.add(key)
                self.turns.append({"role": role, "content": text})
        except Exception as e:
            logger.warning("transcript_accumulator_sync_failed", error=str(e))
