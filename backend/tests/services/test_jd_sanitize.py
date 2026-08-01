"""Deterministic sanitizer tests for jd_sanitize."""
from __future__ import annotations

from app.services.intake.jd_sanitize import MAX_CHARS, sanitize_jd_text


def test_strips_control_chars():
    out, truncated = sanitize_jd_text("Hello\x00\x07World\x1f!")
    assert "\x00" not in out
    assert "\x07" not in out
    assert "Hello" in out and "World" in out
    assert truncated is False


def test_collapses_inline_whitespace():
    out, _ = sanitize_jd_text("a    b\t\tc")
    assert out == "a b c"


def test_collapses_blank_lines():
    out, _ = sanitize_jd_text("a\n\n\n\n\nb")
    assert out == "a\n\nb"


def test_truncates_to_cap():
    out, truncated = sanitize_jd_text("x" * (MAX_CHARS + 500))
    assert truncated is True
    assert len(out) == MAX_CHARS


def test_empty_input():
    assert sanitize_jd_text("") == ("", False)
