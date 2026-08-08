"""The only module in the codebase that speaks to an LLM endpoint.

Talks OpenAI-shaped HTTP to the LiteLLM gateway. Model names are aliases the
gateway resolves to real providers, so provider choice is configuration.
"""

from __future__ import annotations

import inspect
import json
from typing import Any, AsyncIterator

import httpx
import structlog
from openai import AsyncOpenAI

from llm_core.capabilities import CapabilityCache
from llm_core.emulation import build_emulation_instruction, parse_emulated_reply
from llm_core.errors import LLMError
from llm_core.settings import get_settings
from llm_core.types import LLMReply, ToolCall

logger = structlog.get_logger(__name__)

_MAX_LOGGED_KEYS = 10


def _redacted_shape(value: Any) -> dict[str, Any]:
    """Describe model-generated arguments without reproducing any of their values.

    Tool arguments in this product carry candidate names, interview feedback and
    hiring signals, so the payload itself must never reach a log line. Key names
    come from the tool schema rather than the model's prose, which makes them safe
    and enough to debug a malformed reply.
    """
    if isinstance(value, dict):
        return {
            "keys": sorted(str(key) for key in value)[:_MAX_LOGGED_KEYS],
            "size": len(value),
        }
    if isinstance(value, (str, bytes, list, tuple)):
        return {"type": type(value).__name__, "length": len(value)}
    return {"type": type(value).__name__}


def _first_choice(response: Any, alias: str) -> Any:
    """Pull choices[0] without ever raising IndexError or AttributeError.

    Callers catch LLMError. A gateway that answers 200 with an error envelope, an
    empty choices list, or a content-filtered choice carrying no message would
    otherwise throw a shape error straight through those handlers.
    """
    choices = getattr(response, "choices", None)
    if not choices:
        raise LLMError(
            "provider returned no choices; the gateway answered with an unexpected body",
            alias=alias,
        )
    choice = choices[0]
    if getattr(choice, "message", None) is None:
        raise LLMError("provider returned a choice carrying no message", alias=alias)
    return choice


def _message_text(choice: Any, alias: str) -> str:
    """Content as a string. Absent is empty; any other type is a protocol error."""
    content = getattr(choice.message, "content", None)
    if content is None:
        return ""
    if not isinstance(content, str):
        raise LLMError(
            f"provider returned message content of type {type(content).__name__}, "
            "expected a string",
            alias=alias,
        )
    return content


def _slot_key(raw: Any, pending: dict[Any, Any]) -> Any:
    """Which in-flight tool call a streamed delta belongs to.

    `index` is what the OpenAI wire format uses and is all a compliant gateway
    needs. Not every gateway echoes it, though, and reading it as an attribute
    unconditionally turns that omission into a dead turn. The fallbacks keep the
    call assembling: a delta that names an id starts (or continues) that call,
    and an anonymous continuation delta appends to the most recent call — which
    is what it is, since a stream only ever fills one call at a time when it is
    not bothering to index them.
    """
    index = getattr(raw, "index", None)
    if isinstance(index, int):
        return index
    call_id = getattr(raw, "id", None)
    if call_id:
        return f"id:{call_id}"
    if pending:
        return next(reversed(pending))
    return "unindexed"


async def _close_stream(stream: Any) -> None:
    """Best-effort release of the provider's HTTP response.

    A consumer that stops reading part-way — an SSE client disconnecting mid-answer
    is the normal case, not the exceptional one — otherwise leaves the upstream
    response open until the garbage collector gets to it. Failures closing it are
    of no interest to the caller and must never mask the exception already
    unwinding the generator.
    """
    close = getattr(stream, "close", None)
    if close is None:
        return
    try:
        result = close()
        if inspect.isawaitable(result):
            await result
    except Exception:  # noqa: BLE001 — the events are already delivered
        logger.debug("llm_stream_close_failed", exc_info=True)


class LLMClient:
    def __init__(self, openai_client: Any = None, capabilities: Any = None) -> None:
        settings = get_settings()
        self._settings = settings
        self._client = openai_client or AsyncOpenAI(
            base_url=f"{settings.gateway_url}/v1",
            api_key=settings.api_key or "not-needed",
            timeout=settings.timeout_seconds,
            max_retries=0,  # the gateway owns retries
        )
        self._caps = capabilities or CapabilityCache(
            http_get=self._gateway_get,
            forced_json_aliases=settings.force_json_tools,
        )

    async def _gateway_get(self, path: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._settings.api_key}"}
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(f"{self._settings.gateway_url}{path}", headers=headers)
            resp.raise_for_status()
            return resp.json()

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
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature

        outgoing = list(messages)
        emulate = False

        if tools:
            emulate = not await self._caps.supports_tools(model)
            if emulate:
                instruction = build_emulation_instruction(tools)
                outgoing = [{"role": "system", "content": instruction}, *outgoing]
                payload["response_format"] = {"type": "json_object"}
            else:
                payload["tools"] = tools

        if system:
            outgoing = [{"role": "system", "content": system}, *outgoing]

        payload["messages"] = outgoing

        try:
            response = await self._client.chat.completions.create(**payload)
        except Exception as exc:  # noqa: BLE001 — normalize every provider failure
            # openai raises its own hierarchy (APIConnectionError, APITimeoutError,
            # APIStatusError, ...); httpx and the gateway raise others still. Every
            # one of them becomes an LLMError, because that is the only exception
            # type call sites are expected to catch. status_code is present on the
            # SDK's status errors and worth keeping for the retry decisions above us.
            raise LLMError(
                str(exc), alias=model, status=getattr(exc, "status_code", None)
            ) from exc

        # Every shape error in here becomes an LLMError. Five services migrate onto
        # `except LLMError`, so a TypeError from an unexpected gateway body would
        # otherwise land as an unhandled 500 rather than a handled provider failure.
        # BaseException (CancelledError, KeyboardInterrupt) deliberately passes through.
        try:
            return self._to_reply(
                response=response, model=model, tools=tools, emulate=emulate
            )
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 — normalize every malformed body
            raise LLMError(
                f"could not read the provider response: {exc or type(exc).__name__}",
                alias=model,
            ) from exc

    async def stream_turn(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        max_tokens: int = 2048,
    ) -> AsyncIterator[tuple[str, Any]]:
        """Stream one assistant turn as tagged events.

        ('text', str)        — incremental prose
        ('tool_call', {...}) — a completed call: {id, name, input}
        ('done', {...})      — {text, stop_reason}

        Contract copied from the Anthropic-era wrapper so consumers do not change.
        Tool calls are emitted only once their argument JSON is fully assembled.

        stop_reason is the provider's finish_reason passed through untouched, so it
        speaks OpenAI's vocabulary ("stop", "tool_calls", "length"), not Anthropic's
        ("end_turn", "tool_use"). Consumers that branch on the value need a mapping.

        On a model without native tool support the tool schema is pushed into a
        system message, but the reply is NOT parsed back into tool_call events —
        the emulated JSON arrives as ('text', ...) like any other prose. Streaming
        and emulated tools do not compose; use complete() when you need both.
        """
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "stream": True,
        }

        outgoing = list(messages)
        if tools:
            # Guarded: build_emulation_instruction raises on an empty tool list.
            if await self._caps.supports_tools(model):
                payload["tools"] = tools
            else:
                outgoing = [
                    {"role": "system", "content": build_emulation_instruction(tools)},
                    *outgoing,
                ]
        if system:
            outgoing = [{"role": "system", "content": system}, *outgoing]
        payload["messages"] = outgoing

        try:
            stream = await self._client.chat.completions.create(**payload)
        except Exception as exc:  # noqa: BLE001 — normalize every provider failure
            raise LLMError(
                str(exc), alias=model, status=getattr(exc, "status_code", None)
            ) from exc

        text_parts: list[str] = []
        pending: dict[Any, dict[str, Any]] = {}
        stop_reason: str | None = None

        # Everything from here to the end of the loop is normalized to LLMError.
        # A stream that dies mid-response surfaces inside the consumer's `async
        # for`, and a raw ConnectionResetError there sails straight past the
        # `except LLMError` that every call site is written around.
        try:
            async for chunk in stream:
                choices = getattr(chunk, "choices", None)
                if not choices:
                    # Keepalive and usage-only frames carry no choices.
                    continue
                choice = choices[0]

                finish_reason = getattr(choice, "finish_reason", None)
                if finish_reason:
                    stop_reason = finish_reason

                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue

                content = getattr(delta, "content", None)
                if content:
                    if not isinstance(content, str):
                        raise LLMError(
                            "provider streamed a content delta of type "
                            f"{type(content).__name__}, expected a string",
                            alias=model,
                        )
                    text_parts.append(content)
                    yield ("text", content)

                for raw in getattr(delta, "tool_calls", None) or []:
                    slot = pending.setdefault(
                        _slot_key(raw, pending),
                        {"id": None, "name": None, "buf": "", "decoded": None},
                    )
                    if getattr(raw, "id", None):
                        slot["id"] = raw.id
                    fn = getattr(raw, "function", None)
                    if fn is None:
                        continue
                    if getattr(fn, "name", None):
                        slot["name"] = fn.name
                    arguments = getattr(fn, "arguments", None)
                    if not arguments:
                        continue
                    if isinstance(arguments, str):
                        slot["buf"] += arguments
                    else:
                        # Some gateways hand the arguments back already decoded.
                        # Concatenating that would be a TypeError, and the whole
                        # turn would die over a payload that arrived intact.
                        slot["decoded"] = arguments
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 — normalize every provider failure
            raise LLMError(
                f"the stream failed mid-response: {exc or type(exc).__name__}",
                alias=model,
                status=getattr(exc, "status_code", None),
            ) from exc
        finally:
            await _close_stream(stream)

        # Insertion order, not sorted(): slot keys are ints only while the gateway
        # indexes its deltas, and sorting a mix of int and str keys is a TypeError.
        for slot in pending.values():
            if slot["decoded"] is not None:
                parsed: Any = slot["decoded"]
            else:
                try:
                    parsed = json.loads(slot["buf"]) if slot["buf"] else {}
                except json.JSONDecodeError:
                    # A truncated or invalid buffer is the model's fault, not the
                    # transport's, and an empty input lets the caller's own
                    # validation produce the error message. The buffer itself is
                    # model output — in this product it carries candidate names and
                    # hiring signals — so only its shape may reach a log line, and
                    # only as type+length: its keys are model-generated too.
                    logger.warning(
                        "llm_stream_tool_json_invalid",
                        alias=model,
                        name=slot["name"],
                        arguments=_redacted_shape(slot["buf"]),
                    )
                    parsed = {}
            if not isinstance(parsed, dict):
                logger.warning(
                    "llm_stream_tool_arguments_not_an_object",
                    alias=model,
                    name=slot["name"],
                    arguments=_redacted_shape(parsed),
                )
                parsed = {}
            yield ("tool_call", {"id": slot["id"], "name": slot["name"], "input": parsed})

        yield ("done", {"text": "".join(text_parts), "stop_reason": stop_reason})

    def _to_reply(
        self,
        *,
        response: Any,
        model: str,
        tools: list[dict[str, Any]] | None,
        emulate: bool,
    ) -> LLMReply:
        choice = _first_choice(response, model)
        text = _message_text(choice, model)
        finish_reason = getattr(choice, "finish_reason", None)

        if emulate:
            call = parse_emulated_reply(text, tools or [])
            return LLMReply(
                text="",
                model=model,
                tool_calls=[call],
                finish_reason=finish_reason,
                emulated_tools=True,
            )

        calls: list[ToolCall] = []
        for raw in getattr(choice.message, "tool_calls", None) or []:
            function = getattr(raw, "function", None)
            name = getattr(function, "name", None)
            if not name:
                raise LLMError(
                    "provider returned a tool call with no function name", alias=model
                )
            arguments = getattr(function, "arguments", None) or "{}"
            if isinstance(arguments, dict):
                # Some gateways hand the arguments back already decoded. Parsing is
                # then both unnecessary and lossy — json.loads would raise TypeError
                # and discard a perfectly good payload.
                args: dict[str, Any] = arguments
            else:
                try:
                    args = json.loads(arguments)
                except (json.JSONDecodeError, TypeError):
                    # Malformed arguments are the model's fault, not the transport's.
                    # An empty dict lets the caller's own validation produce the error
                    # message, which is more useful than one raised from in here.
                    logger.warning(
                        "llm_tool_arguments_invalid",
                        alias=model,
                        name=name,
                        arguments=_redacted_shape(arguments),
                    )
                    args = {}
                if not isinstance(args, dict):
                    logger.warning(
                        "llm_tool_arguments_not_an_object",
                        alias=model,
                        name=name,
                        arguments=_redacted_shape(args),
                    )
                    args = {}
            calls.append(ToolCall(id=getattr(raw, "id", None) or "", name=name, arguments=args))

        return LLMReply(
            text=text,
            model=model,
            tool_calls=calls,
            finish_reason=finish_reason,
        )


_client: LLMClient | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
