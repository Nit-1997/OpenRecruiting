"""Role-context prompt rendering — open-ended (null max) experience."""

from intake_core.prompts.builder import _role_context_section


def test_renders_open_ended_when_max_is_none():
    section = _role_context_section(
        {"role_name": "Staff Eng", "experience_min": 7, "experience_max": None}
    )
    assert "- Experience: 7+ years" in section
    assert "None" not in section


def test_renders_open_ended_when_max_absent():
    section = _role_context_section({"role_name": "Staff Eng", "experience_min": 7})
    assert "- Experience: 7+ years" in section


def test_renders_range_when_max_present():
    section = _role_context_section(
        {"role_name": "Staff Eng", "experience_min": 7, "experience_max": 11}
    )
    assert "- Experience: 7-11 years" in section
