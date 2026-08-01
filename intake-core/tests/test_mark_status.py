"""Test mark_status tool handler."""

from unittest.mock import MagicMock
import pytest

from intake_core.tools.mark_status import handle_mark_status


@pytest.fixture
def mock_client():
    c = MagicMock()
    c.rpc.return_value.execute = MagicMock()
    return c


def test_mark_status_writes_only_status_field(mock_client):
    out = handle_mark_status(
        client=mock_client,
        session_id="sess-1",
        args={"qid": "q7_team_structure", "status": "skipped"},
    )
    assert out["ok"] is True
    patch = mock_client.rpc.call_args[0][1]["p_patch"]
    assert patch["q7_team_structure"]["status"] == "skipped"
    # Should NOT include text / confidence keys
    assert "text" not in patch["q7_team_structure"]
    assert "extraction_confidence" not in patch["q7_team_structure"]


def test_mark_status_rejects_unknown_qid(mock_client):
    out = handle_mark_status(client=mock_client, session_id="sess-1", args={"qid": "q99", "status": "skipped"})
    assert out["ok"] is False
    mock_client.rpc.assert_not_called()


def test_mark_status_rejects_unknown_status(mock_client):
    out = handle_mark_status(
        client=mock_client, session_id="sess-1",
        args={"qid": "q1_role_overview", "status": "kinda-discussed"},
    )
    assert out["ok"] is False
