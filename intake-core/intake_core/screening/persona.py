"""Generic screening persona + guardrails + Phase-2 structured persona schema.

Phase 1 ships a single generic persona. Phase 2 derives a per-role persona from
the org's real interviewers (Cortex): each of the 5 Cortex-fillable dimensions
gets a synthesized value, `compose_persona` renders them into the persona body,
and the result becomes persona_snapshot['text'] (consumed by build_screening_prompt).
Dimension 6 ('guardrails') is never Cortex-sourced — guardrails come only from
SCREENING_GUARDRAILS and are always appended.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

GENERIC_SCREENING_PERSONA = """\
You are Scout, a warm, professional voice interviewer running a screening round.
Your style: nudging, helpful, probing, and deep — conversational, never robotic.
You lead with curiosity, acknowledge good answers briefly ("got it", "makes sense"),
and probe one or two layers when an answer is worth exploring. You keep the candidate
at ease while still digging for real signal.
"""

SCREENING_GUARDRAILS = """\
NON-NEGOTIABLE RULES:
- Never ask about protected characteristics (age, race, religion, gender, marital/family
  status, disability, national origin) or anything illegal/biased.
- Stay strictly on the configured questions and their topics; do not improvise unrelated areas.
- Never coach the candidate or reveal what a 'good' answer is.
- Stay warm; never hostile, never pressure beyond a normal probe.
- If the candidate goes silent or asks to stop, respond gracefully.
"""

# Phase-2 seam: dimension keys the Cortex persona will fill.
PERSONA_DIMENSIONS = ["tone_rapport", "probing_depth", "eval_priorities",
                      "must_haves", "structure", "guardrails"]

# Human-readable labels for the 5 Cortex-fillable dimensions (NOT guardrails).
DIMENSION_LABELS = {
    "tone_rapport": "Tone & rapport",
    "probing_depth": "Probing depth & follow-up style",
    "eval_priorities": "Evaluation priorities / signals",
    "must_haves": "Must-haves / dealbreakers",
    "structure": "Structure & time budget",
}


@dataclass
class PersonaDimension:
    key: str                  # one of PERSONA_DIMENSIONS
    value: str                # the synthesized description for this dimension
    confidence: float = 0.0   # 0..1
    source: str = "generic"   # "cortex" | "generic" | "recruiter"


@dataclass
class Persona:
    dimensions: list[PersonaDimension] = field(default_factory=list)
    text: str = ""            # compose_persona() output (incl. guardrails)


def compose_persona(dimensions: list[PersonaDimension]) -> str:
    """Render dimensions 1-5 into the persona body and ALWAYS append the
    guardrails (dimension 6 is never Cortex-sourced). The output is valid as
    persona_snapshot['text'] for build_screening_prompt.

    Ordering is deterministic: dimensions present in PERSONA_DIMENSIONS order
    first, then any unknown keys in their given order. The 'guardrails' key is
    ignored as a body line (guardrails come only from SCREENING_GUARDRAILS).
    """
    by_key = {d.key: d for d in dimensions if d.key != "guardrails"}
    ordered_keys = [k for k in PERSONA_DIMENSIONS if k != "guardrails" and k in by_key]
    seen = set(ordered_keys)
    for d in dimensions:
        if d.key != "guardrails" and d.key not in seen:
            ordered_keys.append(d.key)
            seen.add(d.key)

    if ordered_keys:
        body_lines = []
        for key in ordered_keys:
            label = DIMENSION_LABELS.get(key, key)
            body_lines.append(f"{label}: {by_key[key].value}")
        body = "\n".join(body_lines)
    else:
        body = GENERIC_SCREENING_PERSONA

    return f"{body}\n\n{SCREENING_GUARDRAILS}"


def persona_to_snapshot(persona: Persona) -> dict:
    """Serialize a Persona into the DB persona_snapshot shape (Task 4 consumer)."""
    return {"dimensions": [asdict(d) for d in persona.dimensions], "text": persona.text}
