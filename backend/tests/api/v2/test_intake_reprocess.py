"""Integration tests for POST /api/v2/intake/sessions/{id}/reprocess."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.intake_reprocess_service import IntakeReprocessError


SESSION_ID = "11111111-1111-1111-1111-111111111111"
USER_ID = "22222222-2222-2222-2222-222222222222"
ORG_ID = "33333333-3333-3333-3333-333333333333"
PROCESS_RUN_ID = "44444444-4444-4444-4444-444444444444"


@pytest.fixture
def client():
    return TestClient(app)


def _override_auth(user_id=USER_ID, org_id=ORG_ID):
    from app.api.v2.core.dependencies import (
        CurrentUserWithOrg,
        get_current_user_with_org,
    )
    fake_user = MagicMock(id=UUID(user_id))
    fake_current = CurrentUserWithOrg(user=fake_user, organization_id=UUID(org_id))
    app.dependency_overrides[get_current_user_with_org] = lambda: fake_current


def _override_supabase(sb_mock):
    from app.api.v2.core.dependencies import get_supabase
    app.dependency_overrides[get_supabase] = lambda: sb_mock


def test_reprocess_202_on_happy_path(client):
    _override_auth()
    _override_supabase(MagicMock())
    with patch(
        "app.api.v2.routers.intake_reprocess.IntakeReprocessService"
    ) as svc_cls:
        svc = MagicMock()
        svc.reprocess = AsyncMock(return_value={
            "session_id": SESSION_ID,
            "process_run_id": PROCESS_RUN_ID,
        })
        svc_cls.return_value = svc
        resp = client.post(f"/api/v2/intake/sessions/{SESSION_ID}/reprocess")
    assert resp.status_code == 202
    body = resp.json()
    assert body["session_id"] == SESSION_ID
    assert body["process_run_id"] == PROCESS_RUN_ID
    svc.reprocess.assert_awaited_once()
    app.dependency_overrides.clear()


def test_reprocess_409_when_already_running(client):
    _override_auth()
    _override_supabase(MagicMock())
    with patch(
        "app.api.v2.routers.intake_reprocess.IntakeReprocessService"
    ) as svc_cls:
        svc = MagicMock()
        svc.reprocess = AsyncMock(side_effect=IntakeReprocessError(
            "Reprocess already running for this session.", status_code=409
        ))
        svc_cls.return_value = svc
        resp = client.post(f"/api/v2/intake/sessions/{SESSION_ID}/reprocess")
    assert resp.status_code == 409
    assert "already running" in resp.json()["detail"].lower()
    app.dependency_overrides.clear()


def test_reprocess_404_when_session_not_found(client):
    _override_auth()
    _override_supabase(MagicMock())
    with patch(
        "app.api.v2.routers.intake_reprocess.IntakeReprocessService"
    ) as svc_cls:
        svc = MagicMock()
        svc.reprocess = AsyncMock(side_effect=IntakeReprocessError(
            f"Session {SESSION_ID} not found", status_code=404
        ))
        svc_cls.return_value = svc
        resp = client.post(f"/api/v2/intake/sessions/{SESSION_ID}/reprocess")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()
    app.dependency_overrides.clear()


def test_reprocess_500_on_lambda_invoke_failure(client):
    _override_auth()
    _override_supabase(MagicMock())
    with patch(
        "app.api.v2.routers.intake_reprocess.IntakeReprocessService"
    ) as svc_cls:
        svc = MagicMock()
        svc.reprocess = AsyncMock(side_effect=IntakeReprocessError(
            "Failed to invoke reprocess Lambda: boto error", status_code=500
        ))
        svc_cls.return_value = svc
        resp = client.post(f"/api/v2/intake/sessions/{SESSION_ID}/reprocess")
    assert resp.status_code == 500
    assert "lambda" in resp.json()["detail"].lower()
    app.dependency_overrides.clear()
