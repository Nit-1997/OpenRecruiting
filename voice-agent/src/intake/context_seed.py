"""Build the initial OpenAILLMContext message list when resuming a Pipecat
session from an existing intake_sessions row.

Why this lives outside main.py:
  - We want to unit-test the seeding independently of Pipecat (which is hard to
    mock).
  - The text agent (Phase 3) uses the same primer formatting — eventually this
    will move into intake-core, but for Phase 4 we keep it local to the voice
    agent and the text path duplicates the trivial bits.

Tool-call handling:
  We deliberately do NOT replay assistant tool_calls into the resumed context.
  Their side effects already hit the DB. Replaying them would either trigger
  duplicate writes (bad) or be ignored by the model (wasted tokens). We keep
  the assistant's prose only — that's enough to maintain conversational thread.
"""

from __future__ import annotations

from typing import Optional


_MAX_PRIMER_LEN = 240
_MAX_QUOTE_LEN = 140


def format_turn_for_context(turn: dict) -> dict:
    """Convert an intake_sessions.turns entry into an OpenAI-style message dict."""
    return {
        "role": turn["role"],
        "content": turn.get("content", ""),
    }


def build_seed_messages(
    system_prompt: str,
    turns: list[dict],
    primer: Optional[str],
) -> list[dict]:
    """Return [system, *prior_turns, optional_primer] in chronological order.

    `turns` are re-sorted by `idx` defensively.
    `primer`, if provided, is appended as an assistant message — the agent has
    already "said" the continuation line, so when the user speaks next it
    naturally continues the conversation.
    """
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    ordered = sorted(turns, key=lambda t: t.get("idx", 0))
    for t in ordered:
        if not t.get("content"):
            continue
        messages.append(format_turn_for_context(t))

    if primer:
        messages.append({"role": "assistant", "content": primer})

    return messages


def build_continuation_primer(turns: list[dict]) -> Optional[str]:
    """Generate a one-sentence primer referencing the most recent user turn.

    Returns None if there's no prior conversation. We deliberately keep this
    deterministic (string slice) instead of LLM-generated — primer quality
    matters less than primer latency, and a templated reference to the user's
    last input is enough to feel continuous.
    """
    user_turns = [t for t in turns if t.get("role") == "user" and t.get("content")]
    if not user_turns:
        return None

    last = max(user_turns, key=lambda t: t.get("idx", 0))
    quote = last["content"].strip()
    if len(quote) > _MAX_QUOTE_LEN:
        quote = quote[: _MAX_QUOTE_LEN - 1].rsplit(" ", 1)[0] + "…"

    primer = f"Picking up where we left off — you mentioned: \"{quote}\". Let me continue from there."
    if len(primer) > _MAX_PRIMER_LEN:
        primer = primer[: _MAX_PRIMER_LEN - 1] + "…"
    return primer
