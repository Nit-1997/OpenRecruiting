"""Test the v2 session loader — reads intake_sessions row by ID."""

from unittest.mock import MagicMock, patch
import pytest

from src.session_loader import load_intake_session_for_voice, format_turns_for_llm


def test_load_returns_row():
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={
            "id": "sess-1", "form_data": {"role_name": "x"},
            "current_answers": {}, "turns": [], "questions_snapshot": [],
            "active_modality": None, "status": "ready",
        }
    )
    row = load_intake_session_for_voice(mock_client, "sess-1")
    assert row["id"] == "sess-1"


def test_load_raises_when_missing():
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=None)
    with pytest.raises(LookupError):
        load_intake_session_for_voice(mock_client, "nope")


def test_format_turns_for_llm_skips_system_and_empty():
    turns = [
        {"role": "user", "content": "Python is the must-have", "modality": "voice"},
        {"role": "assistant", "content": "", "modality": "voice"},
        {"role": "system", "content": "ignore me"},
        {"role": "assistant", "content": "Got it.", "modality": "text"},
    ]
    out = format_turns_for_llm(turns)
    assert len(out) == 2
    assert out[0]["role"] == "user"
    assert out[1]["role"] == "assistant"
    assert out[1]["content"] == "Got it."


def test_format_turns_preserves_order():
    turns = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
        {"role": "user", "content": "third"},
    ]
    out = format_turns_for_llm(turns)
    assert [t["content"] for t in out] == ["first", "second", "third"]
