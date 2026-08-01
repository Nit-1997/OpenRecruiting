"""TurnPersistFrameProcessor — persist the intake conversation (BOTH roles) to
intake_sessions.turns.

Why messages-based, not frame-interception: the assistant's response frames
(LLMFullResponseStart/Text/End) are emitted by the LLM and flow DOWNSTREAM, so a
processor placed upstream of the LLM (where it needs to be for user transcripts)
never sees them — that's why assistant turns were silently dropped and the
transcript / text-handoff lost all of Scout's lines. Instead we read the shared
LLMContext `messages` list (which the user + assistant aggregators keep updated
with both roles, exactly like v1's end-of-call transcript) and append any new
user/assistant text turns.

Trigger frame: LLMContextFrame, NOT LLMFullResponseEndFrame. This processor sits
AFTER the assistant aggregator, and the assistant aggregator SWALLOWS
LLMFullResponseEndFrame (its process_frame handles it without re-pushing) — so a
downstream processor never receives it. What the aggregator DOES push downstream
is an LLMContextFrame, emitted right after it commits the assistant message to
the shared `messages` list. The user aggregator likewise emits an LLMContextFrame
(with the user message committed) that reaches us first. Syncing on every
LLMContextFrame therefore captures both roles. (Verified against pipecat 0.0.102:
a probe placed after the assistant aggregator receives LLMContextFrame with ctx
roles [system, user, assistant] and never receives LLMFullResponseEndFrame.)

Dedup is by CONTENT, not by position. The assistant aggregator has
context-summarization enabled, which COMPACTS the shared `messages` list in place
(N turns → a single "Conversation summary:" message). A positional high-water
mark (the old `_persisted_count`) silently corrupts the transcript the moment
summarization fires: user turns fall below the stale offset and are dropped,
while early messages (e.g. the greeting) get re-read as "new" and re-persisted.
An append-only set of seen (role, content) signatures survives compaction —
summarized-away turns are already persisted, genuinely new turns persist once,
and the summary message itself is skipped explicitly.

Persistence runs as asyncio.create_task → never blocks the audio path. A DB
failure logs a warning and drops the turn; it never crashes the pipeline.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from pipecat.frames.frames import Frame, LLMContextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from intake_core.persistence import append_turn

logger = structlog.get_logger(__name__)


def build_turn_payload(
    role: str,
    content: str,
    idx: int,
    modality: str,
    tool_calls: Optional[list[dict]] = None,
) -> Optional[dict[str, Any]]:
    """Build the JSONB turn payload. Returns None if content is empty/whitespace."""
    stripped = (content or "").strip()
    if not stripped:
        return None
    payload: dict[str, Any] = {
        "idx": idx,
        "role": role,
        "content": stripped,
        "modality": modality,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if tool_calls:
        payload["tool_calls"] = tool_calls
    return payload


def persist_turn_sync(client, session_id: str, turn: dict[str, Any]) -> None:
    """Call append_turn, swallowing any exception (never block audio path)."""
    try:
        append_turn(client, session_id, turn)
    except Exception as e:
        logger.warning("turn_persist_failed", session_id=session_id, role=turn.get("role"), error=str(e))


def _turn_key(role: str, text: str) -> str:
    """Stable per-turn signature for content-based dedup."""
    return f"{role}\x1f{text}"


# pipecat's context summarizer commits the compacted history as an assistant
# message that begins with this prefix (llm_service._generate_summary). It is not
# a real conversation turn and must never land in the transcript.
_SUMMARY_PREFIX = "conversation summary"


def _text_of(content: Any) -> str:
    """Extract plain text from an LLM message `content` (str or content-block list).

    Anthropic tool turns use a list of blocks; tool_use / tool_result blocks have
    no spoken text and must be skipped so they don't become bogus transcript turns.
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return " ".join(p for p in parts if p).strip()
    return ""


class TurnPersistFrameProcessor(FrameProcessor):
    """Sync the LLMContext conversation → intake_sessions.turns on each LLM turn.

    Place this AFTER the assistant context aggregator so that, on the
    LLMContextFrame the aggregator pushes, `messages` already holds the finalized
    user + assistant turns for the exchange that just completed.
    """

    def __init__(
        self,
        *,
        supabase_client,
        session_id: str,
        messages: Optional[list[dict[str, Any]]] = None,
        on_user_turn: Optional[callable] = None,
        initial_idx: int = 0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._client = supabase_client
        self._session_id = session_id
        self._messages = messages if messages is not None else []  # shared LLMContext list (both roles)
        self._on_user_turn = on_user_turn  # async callback (text: str, idx: int)
        self._next_idx = initial_idx
        self._last_user_turn_idx = 0
        # Content-signature dedup (survives context-summarization compaction).
        # Seed the FIRST initial_idx user/assistant turns — those are the turns
        # already in session.turns (a prior modality on handoff) and must not be
        # re-persisted. Anything beyond initial_idx is a genuinely new turn.
        self._seen: set[str] = set()
        seeded = 0
        for m in self._messages:
            if seeded >= initial_idx:
                break
            if m.get("role") in ("user", "assistant"):
                text = _text_of(m.get("content"))
                if text:
                    self._seen.add(_turn_key(m["role"], text))
                    seeded += 1

    @property
    def current_user_turn_idx(self) -> int:
        """idx of the most recently persisted user turn (tool-call provenance)."""
        return self._last_user_turn_idx

    def _conversation(self) -> list[dict[str, str]]:
        """User/assistant turns that carry real text, in order.

        Skips the system prompt, the synthetic 'say your greeting' system nudges,
        and tool_use / tool_result messages (which have no spoken content).
        """
        out: list[dict[str, str]] = []
        for m in self._messages:
            role = m.get("role")
            if role not in ("user", "assistant"):
                continue
            text = _text_of(m.get("content"))
            if not text:
                continue
            out.append({"role": role, "content": text})
        return out

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame):
            # Read turns off the context the frame carries — the canonical pipecat
            # pattern: the aggregator commits the just-finished turn to its context
            # and pushes LLMContextFrame(context=self._context) downstream
            # (llm_response_universal.py: push_aggregation -> push_context_frame,
            # DOWNSTREAM). In pipecat 0.0.102 this is the SAME list object we were
            # given (LLMContext stores `messages` by reference; set_messages does an
            # in-place `self._messages[:] = ...`), so the captured reference also
            # works today. Preferring the frame's context is strictly more robust:
            # it stays correct even if a future pipecat rebinds the internal list,
            # and it keeps this processor honest about WHERE the turn came from.
            self._adopt_frame_messages(frame)
            self._sync()
        await self.push_frame(frame, direction)

    def _adopt_frame_messages(self, frame: Frame) -> None:
        """Point self._messages at the conversation the frame's context holds.

        No-op (keeps the captured reference) when the frame carries no usable
        context — e.g. older pipecat builds or unit-test fakes."""
        ctx = getattr(frame, "context", None)
        getter = getattr(ctx, "get_messages", None)
        if not callable(getter):
            return
        try:
            msgs = getter()
        except Exception as e:
            logger.warning("turn_frame_context_read_failed", error=str(e))
            return
        if isinstance(msgs, list):
            self._messages = msgs

    def _sync(self) -> None:
        try:
            for turn in self._conversation():
                content = turn["content"]
                # Skip the summarizer's compacted-history message — it is not a turn.
                if turn["role"] == "assistant" and content.lower().startswith(_SUMMARY_PREFIX):
                    continue
                key = _turn_key(turn["role"], content)
                if key in self._seen:
                    continue
                self._seen.add(key)
                idx = self._next_idx
                self._next_idx += 1
                if turn["role"] == "user":
                    self._last_user_turn_idx = idx
                payload = build_turn_payload(
                    role=turn["role"], content=content, idx=idx, modality="voice"
                )
                if payload is None:
                    continue
                logger.info(
                    "turn_persist_scheduled",
                    session_id=self._session_id,
                    idx=idx,
                    role=turn["role"],
                    chars=len(content),
                )
                asyncio.create_task(self._persist_async(payload))
                if turn["role"] == "user" and self._on_user_turn is not None:
                    asyncio.create_task(self._invoke_callback(content, idx))
        except Exception as e:
            logger.warning("turn_sync_failed", session_id=self._session_id, error=str(e))

    async def _persist_async(self, turn: dict[str, Any]) -> None:
        await asyncio.to_thread(persist_turn_sync, self._client, self._session_id, turn)

    async def _invoke_callback(self, user_text: str, idx: int) -> None:
        try:
            await self._on_user_turn(user_text, idx)
        except Exception as e:
            logger.warning("turn_persist_user_callback_failed", error=str(e))
