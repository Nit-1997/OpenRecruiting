"""Test the text vs voice persona variants."""

import pytest
from intake_core.prompts.persona import VOICE_PERSONA, TEXT_PERSONA, get_persona


def test_voice_persona_has_voice_rules():
    assert "1-2 sentences" in VOICE_PERSONA or "1–2 sentences" in VOICE_PERSONA
    assert "[END]" in VOICE_PERSONA
    assert "No markdown" in VOICE_PERSONA or "no markdown" in VOICE_PERSONA.lower()


def test_text_persona_has_text_rules():
    assert "bullet" in TEXT_PERSONA.lower() or "markdown" in TEXT_PERSONA.lower()
    # text mode does NOT use [END] marker per spec §6.4
    assert "[END]" not in TEXT_PERSONA


def test_get_persona_voice():
    assert get_persona("voice") == VOICE_PERSONA


def test_get_persona_text():
    assert get_persona("text") == TEXT_PERSONA


def test_get_persona_unknown_raises():
    with pytest.raises(ValueError):
        get_persona("smoke_signal")
