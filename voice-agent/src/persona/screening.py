"""Dynamic screening persona — wraps intake_core.screening.builder.

The screening agent rebuilds its system prompt every turn from the live session
dict (persona_snapshot, questions, role_context, answered). This module is the
thin adapter the voice agent's screening pipeline calls, mirroring
src/persona/dynamic_intake.py.
"""

from __future__ import annotations

from intake_core.screening.builder import build_screening_prompt


def build_voice_screening_prompt(session: dict) -> str:
    """Assemble the per-turn screening system prompt from the session dict."""
    return build_screening_prompt(session)
