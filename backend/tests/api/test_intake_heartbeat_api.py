"""HTTP tests for /v2/intake/sessions/:id/heartbeat."""
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.v2.core.dependencies import (
    get_current_user_with_org,
    get_supabase,
)


class _StubUser:
    def __init__(self, user_id, org_id):
        self.user = type("U", (), {"id": user_id})()
        self.organization_id = org_id


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def override_auth():
    stub = _StubUser(uuid4(), uuid4())
    app.dependency_overrides[get_current_user_with_org] = lambda: stub
    yield
    app.dependency_overrides.pop(get_current_user_with_org, None)


def test_heartbeat_returns_200_when_lock_held(client, override_auth):
    sid = uuid4()
    with patch("app.api.v2.routers.intake_heartbeat.IntakeHeartbeatService") as svc_cls:
        # ping is async; the route awaits it, so the mock must be awaitable.
        svc_cls.return_value.ping = AsyncMock(return_value="2026-05-28T10:00:00+00:00")
        app.dependency_overrides[get_supabase] = lambda: object()
        try:
            r = client.post(f"/api/v2/intake/sessions/{sid}/heartbeat?paused=false")
        finally:
            app.dependency_overrides.pop(get_supabase, None)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["last_heartbeat_at"] == "2026-05-28T10:00:00+00:00"


def test_heartbeat_returns_409_when_no_lock(client, override_auth):
    from app.services.intake_heartbeat_service import HeartbeatNoLockError
    sid = uuid4()
    with patch("app.api.v2.routers.intake_heartbeat.IntakeHeartbeatService") as svc_cls:
        svc_cls.return_value.ping.side_effect = HeartbeatNoLockError("no lock")
        app.dependency_overrides[get_supabase] = lambda: object()
        try:
            r = client.post(f"/api/v2/intake/sessions/{sid}/heartbeat?paused=true")
        finally:
            app.dependency_overrides.pop(get_supabase, None)
    assert r.status_code == 409
    assert r.json() == {"detail": "modality_lock_not_held"}
