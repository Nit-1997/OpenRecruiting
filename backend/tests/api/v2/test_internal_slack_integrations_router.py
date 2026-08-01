"""Tests for /api/v2/internal/slack-integrations/* (health, force-refresh, backfill).

The router is a thin pass-through to SlackService; we override the internal
secret guard and mock get_slack_service so we exercise the router's error
mapping (409 on reauth-required, 404 on ValueError).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.v2.core.dependencies import verify_internal_secret
from app.main import app
from app.services.slack_service import SlackReauthRequiredError

HEALTH = "/api/v2/internal/slack-integrations/health"
REFRESH = "/api/v2/internal/slack-integrations/refresh/T123"
BACKFILL = "/api/v2/internal/slack-integrations/backfill-auth-state"


@pytest.fixture
def client():
    app.dependency_overrides[verify_internal_secret] = lambda: None
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _service():
    svc = MagicMock()
    svc.get_installation_health_summary = AsyncMock(return_value={"total_active_installations": 2})
    svc.force_refresh_team_token = AsyncMock(return_value={"team_id": "T123", "refreshed": True})
    svc.backfill_auth_state = AsyncMock(return_value={"updated": 1, "skipped": 3})
    return svc


def test_health(client):
    svc = _service()
    with patch("app.api.v2.routers.internal_slack_integrations.get_slack_service", return_value=svc):
        resp = client.get(HEALTH)
    assert resp.status_code == 200
    assert resp.json()["total_active_installations"] == 2


def test_force_refresh_ok(client):
    svc = _service()
    with patch("app.api.v2.routers.internal_slack_integrations.get_slack_service", return_value=svc):
        resp = client.post(REFRESH)
    assert resp.status_code == 200
    assert resp.json()["refreshed"] is True


def test_force_refresh_reauth_required_maps_409(client):
    svc = _service()
    svc.force_refresh_team_token = AsyncMock(side_effect=SlackReauthRequiredError("reauth"))
    with patch("app.api.v2.routers.internal_slack_integrations.get_slack_service", return_value=svc):
        resp = client.post(REFRESH)
    assert resp.status_code == 409


def test_force_refresh_value_error_maps_404(client):
    svc = _service()
    svc.force_refresh_team_token = AsyncMock(side_effect=ValueError("no such team"))
    with patch("app.api.v2.routers.internal_slack_integrations.get_slack_service", return_value=svc):
        resp = client.post(REFRESH)
    assert resp.status_code == 404


def test_backfill(client):
    svc = _service()
    with patch("app.api.v2.routers.internal_slack_integrations.get_slack_service", return_value=svc):
        resp = client.post(BACKFILL)
    assert resp.status_code == 200
    assert resp.json()["updated"] == 1


def test_health_requires_secret(unauthed_client):
    resp = unauthed_client.get(HEALTH)
    assert resp.status_code in (401, 422)
