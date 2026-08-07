"""Happy-path + error-mapping tests for the slack-agent internal endpoints
(create requisition, add candidate, team invite).
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
