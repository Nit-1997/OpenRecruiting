"""Text agent loop for v2 intake.

Streams one assistant turn back to the caller through the LLM gateway as a tagged event iterator,
while:
  - locking the session to text modality
  - persisting user + assistant turns
  - firing the coverage tracker as a background task after the user turn lands
  - executing tool calls (update_answer, mark_status) via intake-core

This module is modality-symmetric with the voice path — they share the same
intake-core primitives (persistence, prompts.builder, tools, coverage_tracker).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import structlog

from intake_core.coverage_tracker import run_coverage_tracker as coverage_tracker_run
from intake_core.persistence import aload_session
from intake_core.prompts.builder import build_dynamic_prompt
from intake_core.tools import INTAKE_TOOLS_OPENAI, ahandle_tool_call

from app.services.intake.llm_stream import stream_llm_turn
from app.services.intake.turn_writer import append_turn_for_session

logger = structlog.get_logger(__name__)

_MAX_TOOL_ITERATIONS = 5

# What each tool must carry to be a real call. A truncated argument buffer arrives
# as input={} (llm_core client.py:436-449). intake-core would refuse it as
# "unknown qid: None", which is safe — but the refusal is unnamed, unlogged, and
# the call was still recorded on the assistant turn as though it had worked.
_REQUIRED_ARGS = {
    spec["function"]["name"]: frozenset(
        spec["function"]["parameters"].get("required") or []
    )
    for spec in INTAKE_TOOLS_OPENAI
}


def _missing_args(tool_call: dict[str, Any]) -> frozenset[str]:
    supplied = set((tool_call.get("input") or {}).keys())
    return _REQUIRED_ARGS.get(tool_call.get("name"), frozenset()) - supplied


# Strong references to in-flight fire-and-forget coverage tasks. CPython only
# keeps a weak reference to a pending asyncio.Task, so without this set the GC
# could collect (and silently cancel) a coverage update mid-run. The done-
# callback discards each task here once it completes and logs any exception so
# failures are never swallowed. (These are asyncio.Task objects bound to the
# running uvicorn event loop, which lives for the process lifetime — this is NOT
# a Lambda handler, so the CLAUDE.md loop-bound-resource teardown rule does not
# apply here.)
_coverage_tasks: set[asyncio.Task] = set()


def _spawn_coverage_task(**coverage_kwargs: Any) -> asyncio.Task:
    """Fire the coverage tracker as a supervised background task.

    Keeps a strong reference (prevents GC-cancellation) and attaches a done-
    callback that surfaces any exception via structured logging — a bare
    asyncio.create_task would let both the reference and the error vanish.
    """
    task = asyncio.create_task(coverage_tracker_run(**coverage_kwargs))
    _coverage_tasks.add(task)
    task.add_done_callback(_on_coverage_task_done)
    return task


def _on_coverage_task_done(task: asyncio.Task) -> None:
    _coverage_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "coverage_tracker_task_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )


class ModalityConflictError(RuntimeError):
    """Raised when a text turn is attempted while voice is the active modality."""


def _format_turns_for_llm(turns: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Convert stored turns into gateway messages format.

    Tool call rounds collapse to plain user/assistant messages — the LLM doesn't
    replay its own tool calls; tool side-effects are persisted out-of-band in
    current_answers (read back via the system prompt's coverage table next turn).
    """
    out: list[dict[str, str]] = []
    for t in turns:
        role = t.get("role")
        content = t.get("content") or ""
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out


async def run_text_opening(
    supabase_client,
    llm,
    model: str,
    session_id: str,
) -> AsyncIterator[tuple[str, Any]]:
    """Generate the agent's next text message WHEN IT HOLDS THE FLOOR.

    This makes the text agent symmetric with voice (which always speaks on
    connect). The floor rule, decided from session.turns:
      - empty session       → warm, role-aware greeting (ephemeral nudge).
      - recruiter spoke last → continuation: respond to the conversation so far,
                               so a voice→text handoff feels like the SAME agent
                               picking up where it left off (no "Say hi to start"
                               dead chat). No new user turn is appended — the
                               existing last user turn IS the prompt.
      - agent spoke last     → no-op; the recruiter already has the floor.

    Streams the greeting/continuation and persists only the assistant turn.
    Yields the same ('text'|'done') events as run_text_turn so the SSE route is
    symmetric. Raises ModalityConflictError if voice is currently active.
    """
    session = await aload_session(supabase_client, session_id)
    if session is None:
        raise LookupError(f"session {session_id} not found")

    if session.get("active_modality") == "voice":
        raise ModalityConflictError(
            "voice mode is currently active for this session; end the voice "
            "session before opening a text conversation"
        )

    turns = session.get("turns") or []
    prior = _format_turns_for_llm(turns)

    # Floor rule: the agent speaks only when it owes a reply. If the last
    # meaningful turn is the agent's, the recruiter has the floor — stay silent.
    if prior and prior[-1]["role"] == "assistant":
        yield ("done", {"text": "", "stop_reason": "noop", "skipped": True})
        return

    # Lock to text + mark active so the modality machine is consistent. (Also
    # re-asserts the lock after a voice→text handoff or a failed voice connect
    # that left active_modality cleared.)
    await (
        supabase_client.table("intake_sessions")
        .update({"active_modality": "text", "status": "active"})
        .eq("id", session_id)
        .execute_async()
    )
    session["active_modality"] = "text"
    session["status"] = "active"

    system_prompt = build_dynamic_prompt(session)
    if prior and prior[-1]["role"] == "user":
        # Continuation — respond to the real conversation (last turn is the
        # recruiter's). Seed the model with the full history so it carries the
        # voice context into text seamlessly.
        messages = prior
    else:
        # Fresh session — ephemeral priming nudge, NOT persisted as a turn. The
        # persona's GREETING rules turn this into a warm, role-aware hello.
        messages = [{"role": "user", "content": "[The recruiter just opened the intake chat.]"}]

    text_parts: list[str] = []
    final_stop_reason: str | None = None
    async for kind, payload in stream_llm_turn(
        llm=llm,
        model=model,
        system=system_prompt,
        messages=messages,
        tools=[],  # greeting only — no tool calls before the recruiter has spoken
    ):
        if kind == "text":
            text_parts.append(payload)
            yield ("text", payload)
        elif kind == "done":
            final_stop_reason = payload.get("stop_reason")

    final_text = "".join(text_parts)
    assistant_turn = await append_turn_for_session(
        supabase_client=supabase_client,
        session_id=session_id,
        role="assistant",
        content=final_text,
        modality="text",
    )
    yield ("done", {
        "text": final_text,
        "stop_reason": final_stop_reason,
        "assistant_turn_idx": assistant_turn["idx"],
    })


async def run_text_turn(
    supabase_client,
    llm,
    model: str,
    session_id: str,
    user_message: str,
) -> AsyncIterator[tuple[str, Any]]:
    """Run one user→assistant turn over text. Yields tagged events.

    ('text', str)       — incremental prose chunk (forward to SSE)
    ('tool_call', dict) — informational; tool already executed by the time this
                          is yielded.
    ('done', dict)      — final metadata: {text, stop_reason, user_turn_idx,
                          assistant_turn_idx}

    Raises ModalityConflictError if voice is currently active.
    """
    session = await aload_session(supabase_client, session_id)
    if session is None:
        raise LookupError(f"session {session_id} not found")

    active = session.get("active_modality")
    if active == "voice":
        raise ModalityConflictError(
            "voice mode is currently active for this session; end the voice "
            "session before sending a text turn"
        )

    # Lock to text + mark session active if it's the first turn
    if active != "text" or session.get("status") != "active":
        await (
            supabase_client.table("intake_sessions")
            .update({"active_modality": "text", "status": "active"})
            .eq("id", session_id)
            .execute_async()
        )
        session["active_modality"] = "text"
        session["status"] = "active"

    # Persist user turn
    user_turn = await append_turn_for_session(
        supabase_client=supabase_client,
        session_id=session_id,
        role="user",
        content=user_message,
        modality="text",
    )

    # Fire coverage tracker as a supervised background task (does NOT block
    # streaming, but is referenced + error-logged via _spawn_coverage_task).
    _spawn_coverage_task(
        supabase_client=supabase_client,
        llm=llm,
        model=model,
        session_id=session_id,
        last_user_turn=user_message,
    )

    # Reload session so the user turn we just appended is visible in turns[]
    fresh_session = await aload_session(supabase_client, session_id)

    system_prompt = build_dynamic_prompt(fresh_session)
    messages = _format_turns_for_llm(fresh_session.get("turns") or [])

    # Accumulate text across all loop iterations (user sees one combined stream)
    all_text_parts: list[str] = []
    all_tool_calls: list[dict[str, Any]] = []
    final_stop_reason: str | None = None

    for iteration in range(_MAX_TOOL_ITERATIONS):
        iteration_text_parts: list[str] = []
        iteration_tool_calls: list[dict[str, Any]] = []

        async for kind, payload in stream_llm_turn(
            llm=llm,
            model=model,
            system=system_prompt,
            messages=messages,
            tools=INTAKE_TOOLS_OPENAI,
        ):
            if kind == "text":
                iteration_text_parts.append(payload)
                all_text_parts.append(payload)
                yield ("text", payload)
            elif kind == "tool_call":
                iteration_tool_calls.append(payload)
            elif kind == "done":
                final_stop_reason = payload.get("stop_reason")

        # Build the assistant content block list for history
        # OpenAI-shaped assistant turn: `content` is a STRING, the calls live in a
        # sibling `tool_calls` array, and `arguments` is a JSON string rather than
        # the decoded dict the tool_call event carried. Both empty forms are
        # omitted rather than sent as null / [] — some providers behind the
        # gateway reject them.
        assistant: dict[str, Any] = {"role": "assistant"}
        iteration_text = "".join(iteration_text_parts)
        if iteration_text or not iteration_tool_calls:
            assistant["content"] = iteration_text
        if iteration_tool_calls:
            assistant["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc.get("input") or {}),
                    },
                }
                for tc in iteration_tool_calls
            ]
        messages.append(assistant)

        # The loop is driven by WHETHER CALLS ARRIVED, not by a stop_reason string.
        # This was `if final_stop_reason != "tool_use": break`, and stream_turn
        # passes the provider's finish_reason through untouched — so the value is
        # "tool_calls" here, and None from a gateway that never sends one. The
        # comparison failed on the first tool-using turn and the loop exited after
        # one iteration having executed nothing, with no error. Correcting the
        # string would leave the same class of bug in place; the presence of calls
        # is what this loop actually depends on. final_stop_reason is still
        # reported in the `done` payload.
        if not iteration_tool_calls:
            break

        if iteration == _MAX_TOOL_ITERATIONS - 1:
            logger.warning(
                "tool_use_loop_guard_hit",
                session_id=session_id,
                iterations=_MAX_TOOL_ITERATIONS,
                stop_reason=final_stop_reason,
            )
            break

        # One {"role": "tool"} message PER CALL, each naming the id it answers.
        # Every entry in the assistant turn's tool_calls must be answered before
        # the next assistant turn or the gateway 400s. This was a single
        # {"role": "user"} message holding every tool_result block, which OpenAI's
        # schema cannot accept at all.
        for tc in iteration_tool_calls:
            tool_name = tc.get("name")
            missing = _missing_args(tc)
            if missing:
                # A degraded call is not dispatched, is not yielded to the caller,
                # and is NOT recorded on the assistant turn — recording it would
                # make a call that did nothing indistinguishable from one that
                # worked. Naming the absent properties lets the model retry.
                logger.warning(
                    "intake_tool_arguments_incomplete",
                    session_id=session_id,
                    name=tool_name,
                    missing=sorted(missing),
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": (
                        "that call was missing required properties: "
                        f"{', '.join(sorted(missing))}"
                    ),
                })
                continue

            try:
                result = await ahandle_tool_call(
                    supabase_client=supabase_client,
                    session_id=session_id,
                    tool_call=tc,
                    turn_idx=user_turn["idx"],
                )
                content = str(result) if result is not None else "ok"
            except Exception as e:
                logger.warning(
                    "tool_call_failed",
                    session_id=session_id,
                    name=tool_name,
                    error=str(e),
                )
                content = f"error: {e}"

            all_tool_calls.append({"name": tool_name, "args": tc.get("input") or {}})
            yield ("tool_call", tc)
            messages.append(
                {"role": "tool", "tool_call_id": tc["id"], "content": content}
            )
        # Continue to next iteration — the model generates its follow-up

    final_text = "".join(all_text_parts)
    assistant_turn = await append_turn_for_session(
        supabase_client=supabase_client,
        session_id=session_id,
        role="assistant",
        content=final_text,
        modality="text",
        tool_calls=all_tool_calls or None,
    )

    yield ("done", {
        "text": final_text,
        "stop_reason": final_stop_reason,
        "user_turn_idx": user_turn["idx"],
        "assistant_turn_idx": assistant_turn["idx"],
    })
