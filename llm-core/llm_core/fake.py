"""In-memory stand-in for LLMClient.

Tests queue outcomes and assert on recorded calls. Nothing here knows about any
provider's wire format, which is the entire point.

Twenty-six test files across five services currently build Anthropic response
objects by hand. They migrate onto this class, which makes it the testing
contract for the whole gateway: if `complete` / `stream_turn` here drift from
the real client's signatures or event shapes, every migrated test passes against
a fake that production can never produce. `tests/test_fake.py` compares both
signatures with `inspect.signature` for exactly that reason.

The governing rule for everything below: the fake must not be *able* to produce
something the real client cannot. Where the two could differ, the fake either
matches the real behaviour or refuses outright.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from llm_core.errors import LLMError
from llm_core.types import LLMReply, ToolCall

# Splits text into deltas that concatenate back to the original exactly —
# leading and trailing whitespace included. Whitespace attaches to the token
# that follows it, so "hi there" streams as "hi" then " there", which is how a
# real token stream arrives.
_DELTA = re.compile(r"\s*\S+|\s+$")


def _as_deltas(text: str) -> list[str]:
    return _DELTA.findall(text or "")


@dataclass
class _Queued:
    """A reply plus the deltas stream_turn should emit for it.

    LLMReply is frozen and carries no notion of chunking, so the delta split
    rides alongside it rather than in it.
    """

    reply: Any
    deltas: list[str] = field(default_factory=list)


class FakeLLM:
    def __init__(self) -> None:
        self._queue: list[Any] = []
        self.calls: list[dict[str, Any]] = []

    def queue_text(self, text: str) -> None:
        """Queue a text reply. Streams as MULTIPLE deltas, like the real client.

        A single-event fake would let every migrated SSE test silently assume one
        text event per turn, which the real client does not guarantee — it yields
        once per content chunk the provider sends. Use queue_text_deltas when the
        exact split matters to the assertion.
        """
        self._queue.append(
            _Queued(
                reply=LLMReply(text=text, model="fake", finish_reason="stop"),
                deltas=_as_deltas(text),
            )
        )

    def queue_text_deltas(self, *parts: str) -> None:
        """Queue a text reply streamed as exactly these deltas, in order.

        For consumers that accumulate or buffer: mid-word splits, empty-ish
        chunks and punctuation-only chunks are all reachable from here.
        """
        text = "".join(parts)
        self._queue.append(
            _Queued(
                reply=LLMReply(text=text, model="fake", finish_reason="stop"),
                # The real client yields only on a truthy content delta, so an
                # empty part is dropped rather than emitted as an empty event.
                deltas=[part for part in parts if part],
            )
        )

    def queue_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        self._queue.append(
            _Queued(
                reply=LLMReply(
                    text="",
                    model="fake",
                    tool_calls=[
                        ToolCall(id=f"fake-{name}", name=name, arguments=arguments)
                    ],
                    finish_reason="tool_calls",
                )
            )
        )

    def queue_reply(self, reply: LLMReply) -> None:
        self._queue.append(
            _Queued(reply=reply, deltas=_as_deltas(getattr(reply, "text", "")))
        )

    def queue_error(self, exc: BaseException) -> None:
        """Queue a failure. A plain Exception is coerced to LLMError.

        Both real methods funnel every provider failure through LLMError, so a
        call site can only ever see that type. Queueing a ValueError as-is would
        let a migrated test wrap `except ValueError` around a call that can never
        raise one — green, and guarding nothing. Coercion (rather than rejection)
        keeps the message and chains the original as __cause__, and leaves
        `queue_error(RuntimeError("boom"))` working, since LLMError is itself a
        RuntimeError.

        BaseExceptions that are not Exceptions — CancelledError, KeyboardInterrupt
        — pass through untouched, because the real client deliberately lets those
        propagate rather than normalizing them.
        """
        self._queue.append(self._as_raisable(exc))

    @staticmethod
    def _as_raisable(exc: BaseException) -> BaseException:
        if isinstance(exc, LLMError) or not isinstance(exc, Exception):
            return exc
        coerced = LLMError(str(exc) or type(exc).__name__)
        coerced.__cause__ = exc
        return coerced

    def _next(self, record: dict[str, Any]) -> _Queued:
        self.calls.append(record)
        assert self._queue, (
            "FakeLLM has no queued response — call queue_text/queue_tool_call/"
            "queue_error before the code under test runs"
        )
        item = self._queue.pop(0)
        if isinstance(item, BaseException):
            raise item

        reply = item.reply
        # Both real methods raise LLMError on a nameless call rather than emit one
        # — complete() in _to_reply, stream_turn() when it drains pending slots.
        # Replaying one would let a migrated test assert on handling for an event
        # production can never produce. Only reachable via queue_reply, since
        # queue_tool_call takes the name as an argument. getattr keeps duck-typed
        # queued objects as legal as they were before the guard.
        for call in getattr(reply, "tool_calls", None) or []:
            if not getattr(call, "name", None):
                raise LLMError(
                    "FakeLLM was queued a tool call with no function name; the real "
                    "client raises on this shape rather than emitting it",
                    alias=record.get("model"),
                )

        # The real client always stamps the reply with the alias it was called
        # with (client.py `_to_reply`), never a provider's own model string. A
        # reply left saying "fake" would make `reply.model` untestable and let an
        # assertion encode a value production never emits.
        if dataclasses.is_dataclass(reply) and not isinstance(reply, type):
            # item.deltas is carried over rather than recomputed: an explicit
            # queue_text_deltas split must survive the restamp.
            return _Queued(
                reply=dataclasses.replace(reply, model=record["model"]),
                deltas=item.deltas,
            )
        return item

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float | None = None,
    ) -> LLMReply:
        return self._next(
            {
                # Snapshotted, matching `outgoing = list(messages)` in the real
                # client. An agent loop appends the assistant turn to the very
                # list it passed in, so storing the reference would let
                # calls[0]["messages"] grow after the fact and a turn-1 assertion
                # would silently read turn-N state.
                "model": model,
                "messages": list(messages),
                "tools": list(tools) if tools is not None else None,
                "system": system,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        ).reply

    async def stream_turn(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        max_tokens: int = 2048,
    ) -> AsyncIterator[tuple[str, Any]]:
        """Replay a queued reply as the real client's event stream.

        ('text', str)        — one event per delta, several per turn. Consumers
                               must accumulate; they may not assume a single event.
        ('tool_call', {...}) — {id, name, input}. `input`, not `arguments`: the
                               event key differs from the ToolCall field name on
                               the real client too.
        ('done', {...})      — {text, stop_reason}. `text` is always the full
                               concatenation of the deltas, however they split.
        """
        queued = self._next(
            {
                "model": model,
                "messages": list(messages),
                "tools": list(tools) if tools is not None else None,
                "system": system,
                "max_tokens": max_tokens,
                "streaming": True,
            }
        )
        reply = queued.reply
        for delta in queued.deltas:
            yield ("text", delta)
        for call in reply.tool_calls:
            yield ("tool_call", {"id": call.id, "name": call.name, "input": call.arguments})
        yield ("done", {"text": reply.text, "stop_reason": reply.finish_reason})
