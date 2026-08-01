"""Test update_answer tool handler — builds the JSONB patch and calls persistence."""

from unittest.mock import MagicMock
import pytest

from intake_core.tools.update_answer import handle_update_answer


@pytest.fixture
def mock_client():
    c = MagicMock()
    c.rpc.return_value.execute = MagicMock()
    return c


def test_update_answer_builds_patch_with_required_fields(mock_client):
    out = handle_update_answer(
        client=mock_client,
        session_id="sess-1",
        args={"qid": "q4_must_haves", "text": "Python, PG, Kafka", "confidence": "high"},
        turn_idx=5,
    )
    assert out["ok"] is True
    mock_client.rpc.assert_called_once()
    rpc_args = mock_client.rpc.call_args
    assert rpc_args[0][0] == "intake_sessions_merge_answers"
    patch = rpc_args[0][1]["p_patch"]
    assert "q4_must_haves" in patch
    a = patch["q4_must_haves"]
    assert a["text"] == "Python, PG, Kafka"
    assert a["extraction_confidence"] == "high"
    assert a["status"] == "discussed"  # default
    assert a["turns_addressed"] == [5]


def test_update_answer_respects_explicit_status(mock_client):
    handle_update_answer(
        client=mock_client,
        session_id="sess-1",
        args={"qid": "q1_role_overview", "text": "payments infra", "confidence": "high", "status": "validated"},
        turn_idx=3,
    )
    patch = mock_client.rpc.call_args[0][1]["p_patch"]
    assert patch["q1_role_overview"]["status"] == "validated"


def test_update_answer_rejects_unknown_qid(mock_client):
    out = handle_update_answer(
        client=mock_client,
        session_id="sess-1",
        args={"qid": "q99_bogus", "text": "x", "confidence": "low"},
        turn_idx=1,
    )
    assert out["ok"] is False
    assert "unknown qid" in out["error"].lower()
    mock_client.rpc.assert_not_called()


def test_update_answer_rejects_bad_confidence(mock_client):
    out = handle_update_answer(
        client=mock_client,
        session_id="sess-1",
        args={"qid": "q1_role_overview", "text": "x", "confidence": "super-high"},
        turn_idx=1,
    )
    assert out["ok"] is False
    mock_client.rpc.assert_not_called()


def test_update_answer_handles_missing_required_field(mock_client):
    out = handle_update_answer(
        client=mock_client,
        session_id="sess-1",
        args={"qid": "q1_role_overview"},  # missing text + confidence
        turn_idx=1,
    )
    assert out["ok"] is False
