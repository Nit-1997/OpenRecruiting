"""Tests for the formal screening persona schema + compose_persona (Phase 2, Task 1)."""

from intake_core.screening.persona import (
    Persona, PersonaDimension, compose_persona, PERSONA_DIMENSIONS, SCREENING_GUARDRAILS)


def test_compose_includes_guardrails_and_all_dims():
    dims = [PersonaDimension(key=k, value=f"v-{k}", confidence=0.9, source="cortex")
            for k in PERSONA_DIMENSIONS if k != "guardrails"]
    text = compose_persona(dims)
    assert "NON-NEGOTIABLE RULES" in text          # guardrails always appended
    for d in dims:
        assert d.value in text


def test_compose_empty_falls_back_to_generic():
    text = compose_persona([])
    assert "NON-NEGOTIABLE RULES" in text
    # body is the generic persona
    from intake_core.screening.persona import GENERIC_SCREENING_PERSONA
    assert GENERIC_SCREENING_PERSONA.strip().split("\n")[0] in text


def test_compose_ignores_guardrails_dimension():
    dims = [PersonaDimension(key="guardrails", value="SHOULD_NOT_APPEAR_AS_BODY", source="cortex"),
            PersonaDimension(key="tone_rapport", value="warm and direct", source="cortex")]
    text = compose_persona(dims)
    assert "warm and direct" in text
    # guardrails dimension value is not injected as a body line (guardrails come from the constant)
    assert "SHOULD_NOT_APPEAR_AS_BODY" not in text


def test_compose_is_valid_persona_snapshot_text():
    # the composed text works as persona_snapshot['text'] in build_screening_prompt
    from intake_core.screening.builder import build_screening_prompt
    text = compose_persona([PersonaDimension(key="tone_rapport", value="warm", source="cortex")])
    prompt = build_screening_prompt({"questions": [], "answered": [],
                                     "persona_snapshot": {"text": text}})
    assert "warm" in prompt
