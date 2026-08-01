"""Load an intake_sessions row and shape turns into OpenAILLMContext messages."""

from __future__ import annotations

from typing import Any


def load_intake_session_for_voice(client, session_id: str) -> dict[str, Any]:
    """Read full intake_sessions row. Raises LookupError when not found."""
    result = (
        client.table("intake_sessions")
        .select("*")
        .eq("id", session_id)
        .single()
        .execute()
    )
    if not result.data:
        raise LookupError(f"intake_sessions row {session_id} not found")
    return result.data


def format_turns_for_llm(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert intake_sessions.turns[] into the message shape Pipecat's
    OpenAILLMContext expects: [{role, content}].

    Skips system turns and empty content. Preserves order.
    """
    out: list[dict[str, Any]] = []
    for t in turns or []:
        role = t.get("role")
        content = (t.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out
