"""Happy-path + error-mapping tests for the slack-agent internal endpoints
(create requisition, intake-call, add candidate, calendar slots, team invite).
The secret guard is overridden; the underlying services are mocked.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.v2.core.dependencies import verify_internal_secret
from app.api.v2.core.exceptions import ConflictError
from app.main import app


@pytest.fixture
def client():
    app.dependency_overrides[verify_internal_secret] = lambda: None
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def test_create_requisition(client):
    req_row = {"id": "req1", "role_title": "Engineer", "role_location": "NYC", "status": "open"}
    with patch("app.api.v2.routers.internal_slack_agent.RequisitionService") as RS, \
         patch("app.api.v2.routers.internal_slack_agent.get_supabase_admin_client", return_value=MagicMock()):
        RS.return_value.create_requisition = AsyncMock(return_value=req_row)
        resp = client.post("/api/v2/internal/requisitions", json={
            "org_id": "o1", "profile_id": "p1", "role_title": "Engineer", "role_location": "NYC",
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "req1"
    assert body["title"] == "Engineer"


def test_intake_call_ok(client):
    svc = MagicMock()
    svc.start_intake_call = AsyncMock(return_value={"intake_call_url": "https://call", "calendar_event_link": None})
    with patch("app.api.v2.routers.internal_slack_agent.get_intake_call_service", return_value=svc):
        resp = client.post("/api/v2/internal/intake-call", json={
            "profile_id": "p1", "org_id": "o1", "requisition_id": "r1",
        })
    assert resp.status_code == 200
    assert resp.json()["intake_call_url"] == "https://call"


def test_intake_call_value_error_400(client):
    svc = MagicMock()
    svc.start_intake_call = AsyncMock(side_effect=ValueError("no calendar connected"))
    with patch("app.api.v2.routers.internal_slack_agent.get_intake_call_service", return_value=svc):
        resp = client.post("/api/v2/internal/intake-call", json={
            "profile_id": "p1", "org_id": "o1", "requisition_id": "r1",
        })
    assert resp.status_code == 400
    assert "no calendar" in resp.json()["detail"]


def test_add_candidate_ok(client):
    svc = MagicMock()
    svc.add_candidate = AsyncMock(return_value={
        "candidate": {"id": "c1"},
        "rounds": [{"candidate_round_id": "cr1", "name": "Round 1", "round_number": 1}],
        "role_title": "Engineer",
    })
    with patch("app.services.candidate_service.get_candidate_service", return_value=svc):
        resp = client.post("/api/v2/internal/candidates", json={
            "org_id": "o1", "requisition_id": "r1", "name": "Alice", "email": "a@x.com",
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["rounds_assigned"] == 1
    assert body["rounds"][0]["candidate_round_id"] == "cr1"


def test_add_candidate_not_found_404(client):
    svc = MagicMock()
    svc.add_candidate = AsyncMock(side_effect=ValueError("requisition not found"))
    with patch("app.services.candidate_service.get_candidate_service", return_value=svc):
        resp = client.post("/api/v2/internal/candidates", json={
            "org_id": "o1", "requisition_id": "r1", "name": "Alice", "email": "a@x.com",
        })
    assert resp.status_code == 404


def test_add_candidate_other_value_error_400(client):
    svc = MagicMock()
    svc.add_candidate = AsyncMock(side_effect=ValueError("duplicate email"))
    with patch("app.services.candidate_service.get_candidate_service", return_value=svc):
        resp = client.post("/api/v2/internal/candidates", json={
            "org_id": "o1", "requisition_id": "r1", "name": "Alice", "email": "a@x.com",
        })
    assert resp.status_code == 400


def test_calendar_slots(client):
    svc = MagicMock()
    svc.find_available_slots = AsyncMock(return_value={"slots": [{"start": "t1"}]})
    with patch("app.api.v2.routers.internal_slack_agent.get_google_calendar_service", return_value=svc):
        resp = client.post("/api/v2/internal/calendar/slots", json={
            "profile_id": "p1", "start_date": "2025-01-01", "end_date": "2025-01-02",
        })
    assert resp.status_code == 200
    assert resp.json()["slots"][0]["start"] == "t1"


def test_team_invite_ok(client):
    with patch("app.api.v2.routers.internal_slack_agent.get_supabase_admin_client", return_value=MagicMock()), \
         patch("app.api.v2.routers.internal_slack_agent.team_service") as ts:
        ts.invite_teammate = AsyncMock(return_value={"id": "inv1", "email": "new@x.com"})
        resp = client.post("/api/v2/internal/team/invite", json={
            "org_id": "o1", "profile_id": "p1", "email": "new@x.com",
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["invite_id"] == "inv1"
    assert body["email"] == "new@x.com"


def test_team_invite_conflict_propagates(client):
    with patch("app.api.v2.routers.internal_slack_agent.get_supabase_admin_client", return_value=MagicMock()), \
         patch("app.api.v2.routers.internal_slack_agent.team_service") as ts:
        ts.invite_teammate = AsyncMock(side_effect=ConflictError("ALREADY_MEMBER", "already a member"))
        resp = client.post("/api/v2/internal/team/invite", json={
            "org_id": "o1", "profile_id": "p1", "email": "dup@x.com",
        })
    assert resp.status_code == 409
