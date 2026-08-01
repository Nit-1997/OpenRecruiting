"""Test the prompt-refresher helper."""

from unittest.mock import MagicMock, patch
import pytest

from src.pipeline.prompt_refresher import refresh_system_prompt


def test_refresh_replaces_system_message():
    context_messages = [
        {"role": "system", "content": "old prompt"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hey"},
    ]
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={
            "form_data": {"role_name": "Senior BE", "experience_min": 5, "experience_max": 8, "location": "NYC"},
            "questions_snapshot": [],
            "current_answers": {},
            "active_modality": "voice",
        }
    )
    refresh_system_prompt(client=mock_client, session_id="s", context_messages=context_messages)
    assert context_messages[0]["role"] == "system"
    assert "You are Scout" in context_messages[0]["content"]
    # Other messages untouched
    assert context_messages[1] == {"role": "user", "content": "hi"}
    assert context_messages[2] == {"role": "assistant", "content": "hey"}


def test_refresh_inserts_system_message_when_missing():
    context_messages = [{"role": "user", "content": "hi"}]
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={"form_data": {"role_name": "x"}, "questions_snapshot": [], "current_answers": {}, "active_modality": "voice"}
    )
    refresh_system_prompt(client=mock_client, session_id="s", context_messages=context_messages)
    assert context_messages[0]["role"] == "system"
    assert context_messages[1]["role"] == "user"


def test_refresh_swallows_db_errors():
    """A refresh failure leaves the existing prompt in place (no crash)."""
    context_messages = [{"role": "system", "content": "old"}]
    mock_client = MagicMock()
    mock_client.table.side_effect = Exception("db down")
    refresh_system_prompt(client=mock_client, session_id="s", context_messages=context_messages)
    # Original prompt preserved
    assert context_messages[0]["content"] == "old"
