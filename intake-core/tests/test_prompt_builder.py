"""Test the dynamic prompt builder — assembles persona + role + coverage + next-move + tools."""

import pytest
from intake_core.prompts.builder import build_dynamic_prompt
from intake_core.questions import snapshot_questions


def _session(form_data=None, current_answers=None, modality="voice"):
    return {
        "id": "abc",
        "form_data": form_data or {"role_name": "Senior Backend Engineer", "experience_min": 5, "experience_max": 8, "location": "NYC"},
        "questions_snapshot": snapshot_questions(),
        "current_answers": current_answers or {},
        "active_modality": modality,
    }


def test_prompt_contains_voice_persona_for_voice_session():
    session = _session(modality="voice")
    prompt = build_dynamic_prompt(session)
    assert "You are Scout" in prompt
    assert "VOICE STYLE" in prompt
    assert "TEXT-SPECIFIC OVERRIDES" not in prompt


def test_prompt_contains_text_override_for_text_session():
    session = _session(modality="text")
    prompt = build_dynamic_prompt(session)
    assert "TEXT-SPECIFIC OVERRIDES" in prompt


def test_prompt_contains_role_context():
    session = _session(form_data={"role_name": "Staff iOS Engineer", "experience_min": 8, "experience_max": 12, "location": "Remote"})
    prompt = build_dynamic_prompt(session)
    assert "Staff iOS Engineer" in prompt
    assert "8" in prompt and "12" in prompt
    assert "Remote" in prompt


def test_prompt_renders_coverage_table_with_all_nine():
    session = _session(current_answers={
        "q1_role_overview": {"status": "validated", "text": "payments infra", "extraction_confidence": "high"},
        "q4_must_haves": {"status": "needs_probe", "text": "Python", "extraction_confidence": "low"},
    })
    prompt = build_dynamic_prompt(session)
    assert "CURRENT COVERAGE" in prompt
    # All 9 question topics should appear in the table
    for q in snapshot_questions():
        assert q["topic"] in prompt
    assert "validated" in prompt
    assert "needs_probe" in prompt
    assert "untouched" in prompt  # the other 7 should be untouched


def test_prompt_contains_next_move_rules():
    session = _session()
    prompt = build_dynamic_prompt(session)
    assert "YOUR NEXT MOVE" in prompt
    assert "NEVER re-ask" in prompt
    assert "[END]" in prompt


def test_prompt_contains_tools_section():
    session = _session()
    prompt = build_dynamic_prompt(session)
    assert "update_answer" in prompt
    assert "mark_status" in prompt


def test_prompt_handles_none_current_answers():
    session = _session(current_answers=None)
    prompt = build_dynamic_prompt(session)
    # Should not crash, all 9 questions render as untouched
    assert "CURRENT COVERAGE" in prompt
    assert prompt.count("untouched") >= 9


def test_prompt_is_stable_string():
    """Snapshot-ish: same input gives same output (no random ordering)."""
    session = _session()
    p1 = build_dynamic_prompt(session)
    p2 = build_dynamic_prompt(session)
    assert p1 == p2
