"""DebriefChatRunner — the bounded Anthropic tool-use loop for debrief chat.

One responsibility: drive a single recruiter→assistant turn over a generated
packet. It owns turn replay, the read-tool loop, the propose interception, the
iteration bound, and fail-soft — and knows nothing about HTTP or persistence
internals (those are the route and the repository).

CQRS guardrail (spec §3.2/§8): read tools run in-loop (executed, grounded); a
propose_* tool is NEVER executed here — calling one ENDS the turn with a single
`proposed_action` event and is persisted on the assistant turn for the FE to
confirm. The runner gates on a name set / prefix so it is forward-compatible with
the action phase without owning the action contract.

Streaming reuses the intake `stream_llm_turn` seam verbatim (same Anthropic SDK
idiom, same mock surface in tests).
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import structlog

from app.services.debrief_chat.contracts import ChatEvent
from app.services.debrief_chat.tool_specs import PROPOSE_TOOL_SPECS, READ_TOOL_SPECS
from app.services.intake.anthropic_stream import stream_llm_turn

logger = structlog.get_logger(__name__)

# The model is offered both read tools (executed in-loop) and propose tools
# (intercepted, never executed). The propose-name set IS the propose tool specs.
_TOOL_SPECS = READ_TOOL_SPECS + PROPOSE_TOOL_SPECS
_READ_TOOL_NAMES = {spec["name"] for spec in READ_TOOL_SPECS}
_PROPOSE_TOOL_NAMES = {spec["name"] for spec in PROPOSE_TOOL_SPECS}
_ERROR_MESSAGE = "Something went wrong answering that. Please try again."
_GRACEFUL_ASSISTANT_TEXT = (
    "I hit a problem answering that just now. Please try asking again."
)


class DebriefChatRunner:
    def __init__(
        self,
        *,
        client,
        model: str,
        max_iters: int,
        max_tokens: int,
        packet_body: dict,
        repo,
        read_tools,
        system_prompt: str,
        packet_id: str,
    ) -> None:
        self._client = client
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
                    client=self._client,
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
                    proposed_action = {
                        "kind": propose_call.get("name"),
                        "input": propose_call.get("input", {}),
                    }
                    yield ChatEvent(type="proposed_action", data=proposed_action)
                    break

                read_calls = [
                    tc for tc in tool_calls if tc.get("name") in _READ_TOOL_NAMES
                ]
                if stop_reason != "tool_use" or not read_calls:
                    break

                if iteration == self._max_iters - 1:
                    logger.warning(
                        "debrief_chat_iteration_guard_hit",
                        packet_id=self._packet_id,
                        max_iters=self._max_iters,
                    )
                    break

                assistant_content: list[dict[str, Any]] = []
                if iteration_text_parts:
                    assistant_content.append(
                        {"type": "text", "text": "".join(iteration_text_parts)}
                    )
                for tc in read_calls:
                    assistant_content.append(
                        {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["name"],
                            "input": tc.get("input", {}),
                        }
                    )
                messages.append({"role": "assistant", "content": assistant_content})

                tool_results: list[dict[str, Any]] = []
                for tc in read_calls:
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
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tc["id"],
                            "content": content,
                        }
                    )
                messages.append({"role": "user", "content": tool_results})
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
