"""Config-time REDUCE: derive a per-role screening persona from the org's real
interviewers.

The "map" already lives in Cortex (interviewer DEMONSTRATES traits). This service
is the "reduce": read that signal once, LLM-synthesize it into the 5 Cortex-
fillable persona dimensions, drop any low-confidence/absent dimension back to a
generic default, render with intake-core's `compose_persona` (which always
appends the guardrails), and persist a `personas` row.

Cold start is first-class: an empty Cortex signal -> ALL dimensions generic, no
LLM call, no raise. The persona text is never re-stated here — it is composed
from the shared intake-core module so the config-time persona and the runtime
voice agent stay anchored to the same wording.

The single LLM call lives behind `_synthesize_dimensions` so tests can mock it.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import structlog
from intake_core.screening.persona import (
    DIMENSION_LABELS,
    PERSONA_DIMENSIONS,
    Persona,
    PersonaDimension,
    compose_persona,
    persona_to_snapshot,
)

from app.config import get_settings
from app.dependencies import get_llm_client
from app.services.supabase import get_supabase_admin_client

from .cortex_persona_reader import CortexPersonaReader

logger = structlog.get_logger(__name__)

# A dimension whose synthesized confidence is below this is treated as no signal
# and replaced by its generic default.
_CONFIDENCE_THRESHOLD = 0.4

# The 5 Cortex-fillable dimensions (guardrails is dimension 6 — never synthesized,
# always appended by compose_persona).
_FILLABLE_DIMENSIONS = [k for k in PERSONA_DIMENSIONS if k != "guardrails"]

# Generic fallback value per dimension, used on cold start or for any dimension
# the LLM could not derive with confidence. These mirror GENERIC_SCREENING_PERSONA
# in tone, split per dimension so compose_persona renders a labelled body.
GENERIC_DIMENSION_VALUES: dict[str, str] = {
    "tone_rapport": (
        "Warm, professional, and conversational; put the candidate at ease while "
        "still digging for real signal."
    ),
    "probing_depth": (
        "Probe one or two layers when an answer is worth exploring — root cause, "
        "trade-offs, what they would do differently — without interrogating."
    ),
    "eval_priorities": (
        "Listen for concrete ownership, depth of execution, and clear reasoning "
        "over rehearsed or surface-level answers."
    ),
    "must_haves": (
        "Confirm the core competencies the role requires; treat the configured "
        "questions as the source of truth for what matters."
    ),
    "structure": (
        "Move through the configured questions in order, keep each focused, and "
        "leave room for the candidate to give a complete answer."
    ),
}


_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_persona_dimensions",
        "description": (
            "Synthesize the org's real interviewer style (provided as trait signal) "
            "into screening-persona dimensions. Each dimension is one paragraph "
            "describing how the screening interviewer should behave for that aspect, "
            "with a confidence reflecting how much real signal supported it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dimensions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "enum": _FILLABLE_DIMENSIONS,
                                "description": "Which persona dimension this describes.",
                            },
                            "value": {
                                "type": "string",
                                "description": "How the interviewer should behave for this dimension.",
                            },
                            "confidence": {
                                "type": "number",
                                "description": "0..1 — how strongly the trait signal supported this.",
                            },
                        },
                        "required": ["key", "value", "confidence"],
                    },
                }
            },
            "required": ["dimensions"],
        },
    },
}


_FORCE_TOOL = {"type": "function", "function": {"name": "emit_persona_dimensions"}}


def _signal_block(signal: list[dict]) -> str:
    lines = []
    for row in signal:
        trait = str(row.get("trait") or "").strip()
        if not trait:
            continue
        category = str(row.get("category") or "").strip()
        evidence = str(row.get("evidence") or "").strip()
        frequency = row.get("frequency")
        parts = [trait]
        if category:
            parts.append(f"[{category}]")
        if frequency is not None:
            parts.append(f"(observed {frequency}x)")
        line = "- " + " ".join(parts)
        if evidence:
            line += f": {evidence}"
        lines.append(line)
    return "\n".join(lines) if lines else "- (no interviewer signal available)"


class PersonaReduceService:
    def __init__(self, supabase=None):
        self.supabase = supabase if supabase is not None else get_supabase_admin_client()
        self.reader = CortexPersonaReader()

    async def derive(
        self,
        *,
        requisition_id: str,
        org_id: str,
        org_name: str,
        role_title: str,
        created_by: str | None,
    ) -> dict:
        """Read Cortex signal, synthesize + generic-fallback the 5 dimensions,
        compose the persona, persist a personas row, and return the API shape.

        Never raises on cold start — always returns a valid (generic) persona.
        """
        signal = await self.reader.read_interviewer_signal(
            org_id=org_id, org_name=org_name, role_title=role_title
        )

        if signal:
            try:
                synthesized = await self._synthesize_dimensions(signal)
            except Exception as exc:  # noqa: BLE001 — fall back to generic on any LLM error
                logger.warning("persona_synthesize_failed", error=str(exc))
                synthesized = []
        else:
            synthesized = []

        dims = self._merge_with_generic(synthesized)
        text = compose_persona(dims)

        persona = Persona(dimensions=dims, text=text)
        snapshot = persona_to_snapshot(persona)

        persona_id = await self.persist_persona(
            requisition_id=requisition_id,
            org_id=org_id,
            role_title=role_title,
            created_by=created_by,
            dimensions=snapshot["dimensions"],
            composed_text=text,
        )

        return {
            "persona_id": persona_id,
            "dimensions": snapshot["dimensions"],
            "composed_text": text,
            "persona_snapshot": snapshot,
        }

    def _merge_with_generic(
        self, synthesized: list[PersonaDimension]
    ) -> list[PersonaDimension]:
        """For each of the 5 fillable dimensions, keep a confident cortex value
        or drop to the generic default. Returns dimensions in canonical order."""
        by_key = {d.key: d for d in synthesized if d.key in GENERIC_DIMENSION_VALUES}
        result: list[PersonaDimension] = []
        for key in _FILLABLE_DIMENSIONS:
            cand = by_key.get(key)
            value = (cand.value or "").strip() if cand else ""
            if cand and value and cand.confidence >= _CONFIDENCE_THRESHOLD:
                result.append(
                    PersonaDimension(
                        key=key,
                        value=value,
                        confidence=float(cand.confidence),
                        source="cortex",
                    )
                )
            else:
                result.append(
                    PersonaDimension(
                        key=key,
                        value=GENERIC_DIMENSION_VALUES[key],
                        confidence=0.0,
                        source="generic",
                    )
                )
        return result

    async def _synthesize_dimensions(
        self, signal: list[dict]
    ) -> list[PersonaDimension]:
        """Single LLM seam. Forces the emit_persona_dimensions tool call and
        maps its output to PersonaDimension(source='cortex')."""
        labels = "\n".join(
            f"- {key}: {DIMENSION_LABELS.get(key, key)}" for key in _FILLABLE_DIMENSIONS
        )
        prompt = f"""You are deriving a voice-screening interviewer persona for one role from
how this organization's REAL interviewers actually conduct interviews.

Below is the observed interviewer-style signal from past interviews (trait,
category, evidence, and how often it was observed):

<interviewer_signal>
{_signal_block(signal)}
</interviewer_signal>

Synthesize this into these persona dimensions:
{labels}

For each dimension write one short paragraph describing how the screening
interviewer should behave, grounded in the signal above. Set confidence 0..1
reflecting how much real signal supported that dimension — use a LOW confidence
(below 0.4) when the signal says little or nothing about that dimension, so it
can fall back to a sensible generic default. Never invent traits the signal does
not support.

Respond ONLY by calling emit_persona_dimensions."""

        llm = get_llm_client()
        model = get_settings().PERSONA_REDUCE_MODEL
        reply = await llm.complete(
            model=model,
            max_tokens=2000,
            tools=[_TOOL],
            tool_choice=_FORCE_TOOL,
            messages=[{"role": "user", "content": prompt}],
        )
        call = reply.tool_call_named("emit_persona_dimensions")
        raw_dims: list[dict[str, Any]] = (call.arguments.get("dimensions") or []) if call else []

        dims: list[PersonaDimension] = []
        for raw in raw_dims:
            if not isinstance(raw, dict):
                continue
            key = (raw.get("key") or "").strip()
            if key not in GENERIC_DIMENSION_VALUES:
                continue
            value = (raw.get("value") or "").strip()
            try:
                confidence = float(raw.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            dims.append(
                PersonaDimension(
                    key=key,
                    value=value,
                    confidence=max(0.0, min(1.0, confidence)),
                    source="cortex",
                )
            )
        return dims

    async def persist_persona(
        self,
        *,
        requisition_id: str,
        org_id: str,
        role_title: str,
        created_by: str | None,
        dimensions: list[dict],
        composed_text: str,
    ) -> str | None:
        payload = {
            "organization_id": org_id,
            "requisition_id": requisition_id,
            "name": f"Screening persona — {role_title}".strip(),
            "dimensions": dimensions,
            "composed_text": composed_text,
        }
        if created_by:
            payload["created_by"] = created_by
        result = await self.supabase.table("personas").insert(payload).execute_async()
        row = result.data or {}
        return row.get("id") if isinstance(row, dict) else None
