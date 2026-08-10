"""DebriefChatRunner — the bounded gateway tool-use loop for debrief chat.

One responsibility: drive a single recruiter→assistant turn over a generated
packet. It owns turn replay, the read-tool loop, the propose interception, the
iteration bound, and fail-soft — and knows nothing about HTTP or persistence
internals (those are the route and the repository).

CQRS guardrail (spec §3.2/§8): read tools run in-loop (executed, grounded); a
propose_* tool is NEVER executed here — calling one ENDS the turn with a single
`proposed_action` event and is persisted on the assistant turn for the FE to
confirm. The runner gates on a name set / prefix so it is forward-compatible with
the action phase without owning the action contract.

Streaming goes through the intake `stream_llm_turn` seam over llm_core, so the
model is a gateway alias and nothing here names a provider. The in-loop request
history is OpenAI-shaped: an assistant message carrying a sibling `tool_calls`
array whose arguments are a JSON STRING, followed by one
{"role": "tool", "tool_call_id": ...} message per call. It was Anthropic content
blocks before phase 3, which OpenAI's Chat Completions schema cannot accept.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import structlog

from app.services.debrief_chat.contracts import ChatEvent
from app.services.debrief_chat.tool_specs import PROPOSE_TOOL_SPECS, READ_TOOL_SPECS
from app.services.intake.llm_stream import stream_llm_turn

logger = structlog.get_logger(__name__)

# The model is offered both read tools (executed in-loop) and propose tools
# (intercepted, never executed). The propose-name set IS the propose tool specs.
_TOOL_SPECS = READ_TOOL_SPECS + PROPOSE_TOOL_SPECS
_READ_TOOL_NAMES = {spec["function"]["name"] for spec in READ_TOOL_SPECS}
_PROPOSE_TOOL_NAMES = {spec["function"]["name"] for spec in PROPOSE_TOOL_SPECS}

# What each tool must carry to be a real call. A truncated argument buffer
# arrives as input={} (llm_core client.py:436-449) and is otherwise
# indistinguishable from a genuine call of all-defaults — the recurring failure
# shape in this codebase, found three times in phase 2. Keyed on the schema's
# declared `required` set, as those fixes were.
_REQUIRED_ARGS = {
    spec["function"]["name"]: frozenset(
        spec["function"]["parameters"].get("required") or []
    )
    for spec in _TOOL_SPECS
}


def _missing_args(tool_call: dict) -> frozenset[str]:
    """Required properties absent from a streamed call's arguments."""
    supplied = set((tool_call.get("input") or {}).keys())
    return _REQUIRED_ARGS.get(tool_call.get("name"), frozenset()) - supplied


_ERROR_MESSAGE = "Something went wrong answering that. Please try again."
_GRACEFUL_ASSISTANT_TEXT = (
    "I hit a problem answering that just now. Please try asking again."
)


class DebriefChatRunner:
    def __init__(
        self,
        *,
        llm,
        model: str,
        max_iters: int,
        max_tokens: int,
        packet_body: dict,
        repo,
        read_tools,
        system_prompt: str,
        packet_id: str,
    ) -> None:
        self._llm = llm
        self._model = model
        self._max_iters = max_iters
        self._max_tokens = max_tokens
        self._packet_body = packet_body
        self._repo = repo
        self._read_tools = read_tools
        self._system_prompt = system_prompt
        self._packet_id = packet_id

    @staticmethod
    def _replay_history(turns: list[dict]) -> list[dict[str, str]]:
        """Stored turns -> Anthropic messages. Tool rounds collapse to plain text
        (the propose action lives on the turn, not replayed as a tool_use block)."""
        out: list[dict[str, str]] = []
        for turn in turns:
            role = turn.get("role")
            text = turn.get("text") or ""
            if role in ("user", "assistant") and text:
                out.append({"role": role, "content": text})
        return out

    async def run(self, message: str) -> AsyncIterator[ChatEvent]:
        all_text_parts: list[str] = []
        proposed_action: dict | None = None

        try:
            await self._repo.append_turn(
                self._packet_id, {"role": "user", "text": message}
            )

            # append_turn commits the user turn, so the reload already includes it.
            # The reloaded turns ARE the complete messages array — re-appending the
            # current message would produce two consecutive identical user messages
            # (rejected/degraded by the Anthropic Messages API). Matches the intake
            # text_runner.mutate_runner reference.
            messages: list[dict[str, Any]] = self._replay_history(
                await self._repo.load_turns(self._packet_id)
            )

            for iteration in range(self._max_iters):
                iteration_text_parts: list[str] = []
                tool_calls: list[dict[str, Any]] = []
                stop_reason: str | None = None

                async for kind, payload in stream_llm_turn(
                    llm=self._llm,
                    model=self._model,
                    system=self._system_prompt,
                    messages=messages,
                    tools=_TOOL_SPECS,
                    max_tokens=self._max_tokens,
                ):
                    if kind == "text":
                        iteration_text_parts.append(payload)
                        all_text_parts.append(payload)
                        yield ChatEvent(type="token", data=payload)
                    elif kind == "tool_call":
                        tool_calls.append(payload)
                    elif kind == "done":
                        stop_reason = payload.get("stop_reason")

                propose_call = next(
                    (tc for tc in tool_calls if tc.get("name") in _PROPOSE_TOOL_NAMES),
                    None,
                )
                if propose_call is not None:
                    missing = _missing_args(propose_call)
                    if missing:
                        # A degraded reply must never become a confirm card. This
                        # one would propose a write against a real candidate while
                        # naming neither the candidate nor the verdict, and it is
                        # persisted on the turn — the same shape as phase 2's
                        # fabricated authenticity verdict. The turn falls through
                        # and ends as text, which is what the model produced.
                        logger.warning(
                            "debrief_chat_propose_arguments_incomplete",
                            packet_id=self._packet_id,
                            tool=propose_call.get("name"),
                            missing=sorted(missing),
                        )
                    else:
                        proposed_action = {
                            "kind": propose_call.get("name"),
                            "input": propose_call.get("input", {}),
                        }
                        yield ChatEvent(type="proposed_action", data=proposed_action)
                        break

                read_calls = [
                    tc for tc in tool_calls if tc.get("name") in _READ_TOOL_NAMES
                ]
                # Driven by whether calls arrived, NOT by a stop_reason string.
                # This was `stop_reason != "tool_use"`, and stream_turn passes the
                # provider's finish_reason through untouched — so the value is
                # "tool_calls" today and None from a gateway that omits it.
                # Correcting the string would leave the same class of bug in
                # place; presence of calls is what the loop actually depends on.
                if not read_calls:
                    break

                if iteration == self._max_iters - 1:
                    logger.warning(
                        "debrief_chat_iteration_guard_hit",
                        packet_id=self._packet_id,
                        max_iters=self._max_iters,
                        stop_reason=stop_reason,
                    )
                    break

                # OpenAI-shaped assistant turn: content is a STRING, the calls
                # live in a sibling `tool_calls` array, and `arguments` is a JSON
                # string rather than the decoded dict the event carried. Both
                # empty forms are omitted: some providers behind the gateway
                # reject content: null and tool_calls: [].
                assistant: dict[str, Any] = {"role": "assistant"}
                text = "".join(iteration_text_parts)
                if text:
                    assistant["content"] = text
                assistant["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc.get("input") or {}),
                        },
                    }
                    for tc in read_calls
                ]
                messages.append(assistant)

                # One {"role": "tool"} message PER CALL, each carrying the id it
                # answers. Every entry in the assistant turn's tool_calls must be
                # answered before the next assistant turn or the gateway 400s.
                for tc in read_calls:
                    missing = _missing_args(tc)
                    if missing:
                        # Not dispatched: the arguments are degraded, and telling
                        # the model exactly what is absent lets the next iteration
                        # retry. Dispatching {} would reach the same refusal from
                        # DebriefReadTools, but unnamed and unlogged.
                        logger.warning(
                            "debrief_chat_read_arguments_incomplete",
                            packet_id=self._packet_id,
                            tool=tc.get("name"),
                            missing=sorted(missing),
                        )
                        content = (
                            "that call was missing required properties: "
                            f"{', '.join(sorted(missing))}"
                        )
                    else:
                        try:
                            result = await self._read_tools.dispatch(
                                tc["name"], tc.get("input", {})
                            )
                            content = str(result)
                        except Exception as exc:  # noqa: BLE001 — per-tool fail-soft
                            logger.warning(
                                "debrief_chat_read_tool_failed",
                                packet_id=self._packet_id,
                                tool=tc.get("name"),
                                error=str(exc),
                            )
                            content = "couldn't fetch that data right now"
                    messages.append(
                        {"role": "tool", "tool_call_id": tc["id"], "content": content}
                    )
        except Exception:
            logger.exception("debrief_chat_turn_failed", packet_id=self._packet_id)
            yield ChatEvent(type="error", data={"message": _ERROR_MESSAGE})
            turn_idx = None
            try:
                assistant_turn = await self._repo.append_turn(
                    self._packet_id,
                    {
                        "role": "assistant",
                        "text": _GRACEFUL_ASSISTANT_TEXT,
                        "proposed_action": None,
                    },
                )
                turn_idx = assistant_turn.get("idx")
            except Exception:
                # The repo itself may be the failure (e.g. entry append_turn). Don't
                # let the graceful-persist re-raise out of the generator.
                logger.exception(
                    "debrief_chat_graceful_persist_failed", packet_id=self._packet_id
                )
            yield ChatEvent(type="done", data={"turn_idx": turn_idx})
            return

        assistant_turn = await self._repo.append_turn(
            self._packet_id,
            {
                "role": "assistant",
                "text": "".join(all_text_parts),
                "proposed_action": proposed_action,
            },
        )
        yield ChatEvent(type="done", data={"turn_idx": assistant_turn.get("idx")})
