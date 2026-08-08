"""In-memory stand-in for LLMClient.

Tests queue outcomes and assert on recorded calls. Nothing here knows about any
provider's wire format, which is the entire point.

Twenty-six test files across five services currently build Anthropic response
objects by hand. They migrate onto this class, which makes it the testing
contract for the whole gateway: if `complete` / `stream_turn` here drift from
the real client's signatures or event shapes, every migrated test passes against
a fake that production can never produce. `tests/test_fake.py` compares both
signatures with `inspect.signature` for exactly that reason.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from llm_core.errors import LLMError
from llm_core.types import LLMReply, ToolCall


class FakeLLM:
    def __init__(self) -> None:
        self._queue: list[Any] = []
        self.calls: list[dict[str, Any]] = []

    def queue_text(self, text: str) -> None:
        self._queue.append(LLMReply(text=text, model="fake", finish_reason="stop"))

    def queue_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        self._queue.append(
            LLMReply(
                text="",
                model="fake",
                tool_calls=[ToolCall(id=f"fake-{name}", name=name, arguments=arguments)],
                finish_reason="tool_calls",
            )
        )

    def queue_reply(self, reply: LLMReply) -> None:
        self._queue.append(reply)

    def queue_error(self, exc: Exception) -> None:
        self._queue.append(exc)

    def _next(self, record: dict[str, Any]) -> LLMReply:
        self.calls.append(record)
        assert self._queue, (
            "FakeLLM has no queued response — call queue_text/queue_tool_call/"
            "queue_error before the code under test runs"
        )
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        # Both real methods raise LLMError on a nameless call rather than emit one
        # — complete() in _to_reply, stream_turn() when it drains pending slots.
        # Replaying one here would let a migrated test assert on handling for an
        # event production can never produce, which is the failure this class
        # exists to prevent. Only reachable via queue_reply, since queue_tool_call
        # takes the name as an argument. getattr keeps duck-typed queued objects
        # as legal as they were before the guard.
        for call in getattr(item, "tool_calls", None) or []:
            if not getattr(call, "name", None):
                raise LLMError(
                    "FakeLLM was queued a tool call with no function name; the real "
                    "client raises on this shape rather than emitting it",
                    alias=record.get("model"),
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
                "model": model,
                "messages": messages,
                "tools": tools,
                "system": system,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )

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

        ('text', str)        — the whole reply in one event; the real client
                               emits many, and consumers must not assume either.
        ('tool_call', {...}) — {id, name, input}. `input`, not `arguments`: the
                               event key differs from the ToolCall field name on
                               the real client too.
        ('done', {...})      — {text, stop_reason}, stop_reason being the
                               queued reply's finish_reason.
        """
        reply = self._next(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "system": system,
                "max_tokens": max_tokens,
                "streaming": True,
            }
        )
        if reply.text:
            yield ("text", reply.text)
        for call in reply.tool_calls:
            yield ("tool_call", {"id": call.id, "name": call.name, "input": call.arguments})
        yield ("done", {"text": reply.text, "stop_reason": reply.finish_reason})
