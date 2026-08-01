"""Dynamic intake persona — wraps intake_core.prompts.builder.

The v2 agent builds the system prompt every turn from the live intake_sessions
row. This module is the thin adapter the v2 main.py calls.
"""

from __future__ import annotations

from typing import Any

from intake_core.prompts.builder import build_dynamic_prompt


def build_voice_intake_prompt(session_row: dict[str, Any]) -> str:
    """Force voice modality and call the shared dynamic builder."""
    # Ensure active_modality is set to voice in case the row hasn't been updated yet.
    session_for_prompt = {**session_row, "active_modality": "voice"}
    return build_dynamic_prompt(session_for_prompt)
