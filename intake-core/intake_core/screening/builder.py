"""Dynamic screening prompt builder — assembles the system prompt every turn.

Pure function: given the same session dict, returns the same string. No I/O,
no LLM calls. Mirrors intake_core.prompts.builder.

Phase-2 seam: `persona_snapshot` (dict with a 'text' key) overrides the generic
persona when present; otherwise we fall back to GENERIC_SCREENING_PERSONA.
"""

from __future__ import annotations

from .persona import GENERIC_SCREENING_PERSONA, SCREENING_GUARDRAILS


def build_screening_prompt(session: dict) -> str:
    """Assemble the system prompt each turn. `session` carries:
       persona_snapshot (dict|None with a 'text' key), questions (list[dict]),
       role_context (str), answered (iterable of covered question ids)."""
    persona = (session.get("persona_snapshot") or {}).get("text") or GENERIC_SCREENING_PERSONA
    role_ctx = session.get("role_context", "")
    questions = session.get("questions", [])
    answered = set(session.get("answered", []))

    lines = [persona, "", "ROLE CONTEXT:", role_ctx, "", "QUESTIONS TO COVER:"]
    for q in questions:
        glyph = "[done]" if q["id"] in answered else "[ ]"
        lines.append(f"{glyph} ({q.get('signal','')}) {q['prompt']}")
        if q.get("probe"):
            lines.append(f"      probe: {q['probe']}")
    lines += ["", "NEXT MOVE:",
              "- Ask the next uncovered question; probe 1-2 layers when worthwhile.",
              "- Never re-ask a [done] question.",
              "- When all questions are covered, thank the candidate and wrap up.",
              "", SCREENING_GUARDRAILS]
    return "\n".join(lines)
