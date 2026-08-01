"""Refresh the LLMContext's system message before each LLM run.

Tool calls and the coverage tracker mutate current_answers between turns —
the next LLM call needs the updated coverage table reflected in its prompt.
"""

from __future__ import annotations

from typing import Any

import structlog

from src.persona.dynamic_intake import build_voice_intake_prompt
from src.session_loader import load_intake_session_for_voice

logger = structlog.get_logger(__name__)


def refresh_system_prompt(
    client,
    session_id: str,
    context_messages: list[dict[str, Any]],
) -> None:
    """In-place rewrite of context_messages[0] (system) to reflect current state.

    On any failure (DB error, missing row), leaves context_messages unchanged.
    """
    try:
        row = load_intake_session_for_voice(client, session_id)
    except Exception as e:
        logger.warning("prompt_refresh_load_failed", session_id=session_id, error=str(e))
        return

    try:
        new_prompt = build_voice_intake_prompt(row)
    except Exception as e:
        logger.warning("prompt_refresh_build_failed", session_id=session_id, error=str(e))
        return

    if context_messages and context_messages[0].get("role") == "system":
        context_messages[0]["content"] = new_prompt
    else:
        context_messages.insert(0, {"role": "system", "content": new_prompt})
