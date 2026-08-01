"""Validation-branch tests for POST /api/v2/internal/calendar-intelligence/schedule.

Exercises the early guards (secret, feature-flag, detection-not-found,
terminal-state, CAS-claim, requisition + round validation) without driving the
full happy path. The inline verify_internal_secret reads settings via
get_settings; we patch it in the router module + app.config.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

ENDPOINT = "/api/v2/internal/calendar-intelligence/schedule"
SECRET = "cal-intel-secret"


def _body(**over):
    base = dict(
        detection_id="d1", candidate_name="Alice", candidate_email="alice@x.com",
        requisition_id="req1", round_id="rd1",
    )
    base.update(over)
    return base


def _settings(enabled=True):
    return SimpleNamespace(INTERNAL_API_SECRET=SECRET, CALENDAR_INTELLIGENCE_ENABLED=enabled)


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _table_supabase(results):
    sb = MagicMock()

    def table(name):
        builder = MagicMock()
        for attr in ("select", "update", "insert", "eq", "is_"):
            setattr(builder, attr, MagicMock(return_value=builder))
        builder.execute_async = AsyncMock(return_value=results.get(name, MagicMock(data=[])))
        return builder

    sb.table = MagicMock(side_effect=table)
    return sb


def _res(data):
    return MagicMock(data=data)


def test_bad_secret_403(client):
    with patch("app.config.get_settings", _settings), \
         patch("app.api.v2.routers.internal_calendar_intelligence.get_settings", _settings):
        resp = client.post(ENDPOINT, headers={"X-Internal-Secret": "wrong"}, json=_body())
    assert resp.status_code == 403


def test_feature_disabled_503(client):
    with patch("app.config.get_settings", lambda: _settings(enabled=False)), \
         patch("app.api.v2.routers.internal_calendar_intelligence.get_settings", lambda: _settings(enabled=False)):
        resp = client.post(ENDPOINT, headers={"X-Internal-Secret": SECRET}, json=_body())
    assert resp.status_code == 503


def test_detection_not_found_404(client):
    sb = _table_supabase({"calendar_event_detections": _res([])})
    with patch("app.config.get_settings", _settings), \
         patch("app.api.v2.routers.internal_calendar_intelligence.get_settings", _settings), \
         patch("app.api.v2.routers.internal_calendar_intelligence.get_supabase_admin_client", return_value=sb):
        resp = client.post(ENDPOINT, headers={"X-Internal-Secret": SECRET}, json=_body())
    assert resp.status_code == 404


def test_terminal_state_409(client):
    sb = _table_supabase({"calendar_event_detections": _res([
        {"id": "d1", "detection_status": "confirmed", "organization_id": "o1", "profile_id": "p1"},
    ])})
    with patch("app.config.get_settings", _settings), \
         patch("app.api.v2.routers.internal_calendar_intelligence.get_settings", _settings), \
         patch("app.api.v2.routers.internal_calendar_intelligence.get_supabase_admin_client", return_value=sb):
        resp = client.post(ENDPOINT, headers={"X-Internal-Secret": SECRET}, json=_body())
    assert resp.status_code == 409


def test_cas_claim_lost_409(client):
    sb = MagicMock()
    calls = {"n": 0}

    def table(name):
        builder = MagicMock()
        for attr in ("select", "update", "eq", "is_"):
            setattr(builder, attr, MagicMock(return_value=builder))
        if name == "calendar_event_detections":
            async def exec_async():
                calls["n"] += 1
                if calls["n"] == 1:
                    return MagicMock(data=[{"id": "d1", "detection_status": "detected", "organization_id": "o1", "profile_id": "p1"}])
                return MagicMock(data=[])  # CAS claim lost
            builder.execute_async = AsyncMock(side_effect=exec_async)
        else:
            builder.execute_async = AsyncMock(return_value=MagicMock(data=[]))
        return builder

    sb.table = MagicMock(side_effect=table)
    with patch("app.config.get_settings", _settings), \
         patch("app.api.v2.routers.internal_calendar_intelligence.get_settings", _settings), \
         patch("app.api.v2.routers.internal_calendar_intelligence.get_supabase_admin_client", return_value=sb):
        resp = client.post(ENDPOINT, headers={"X-Internal-Secret": SECRET}, json=_body())
    assert resp.status_code == 409


def test_requisition_not_found_404(client):
    sb = MagicMock()
    state = {"det": 0}

    def table(name):
        builder = MagicMock()
        for attr in ("select", "update", "eq", "is_"):
            setattr(builder, attr, MagicMock(return_value=builder))
        if name == "calendar_event_detections":
            async def exec_async():
                state["det"] += 1
                # 1st = lookup, 2nd = CAS claim (wins), 3rd = rollback
                if state["det"] == 1:
                    return MagicMock(data=[{"id": "d1", "detection_status": "detected", "organization_id": "o1", "profile_id": "p1"}])
                return MagicMock(data=[{"id": "d1"}])
            builder.execute_async = AsyncMock(side_effect=exec_async)
        elif name == "requisitions":
            builder.execute_async = AsyncMock(return_value=MagicMock(data=[]))  # not found
        else:
            builder.execute_async = AsyncMock(return_value=MagicMock(data=[]))
        return builder

    sb.table = MagicMock(side_effect=table)
    with patch("app.config.get_settings", _settings), \
         patch("app.api.v2.routers.internal_calendar_intelligence.get_settings", _settings), \
         patch("app.api.v2.routers.internal_calendar_intelligence.get_supabase_admin_client", return_value=sb):
        resp = client.post(ENDPOINT, headers={"X-Internal-Secret": SECRET}, json=_body())
    assert resp.status_code == 404


def test_org_mismatch_400(client):
    sb = MagicMock()
    state = {"det": 0}

    def table(name):
        builder = MagicMock()
        for attr in ("select", "update", "eq", "is_"):
            setattr(builder, attr, MagicMock(return_value=builder))
        if name == "calendar_event_detections":
            async def exec_async():
                state["det"] += 1
                if state["det"] == 1:
                    return MagicMock(data=[{"id": "d1", "detection_status": "detected", "organization_id": "o1", "profile_id": "p1"}])
                return MagicMock(data=[{"id": "d1"}])
            builder.execute_async = AsyncMock(side_effect=exec_async)
        elif name == "requisitions":
            builder.execute_async = AsyncMock(return_value=MagicMock(data=[{"id": "req1", "organization_id": "OTHER_ORG"}]))
        else:
            builder.execute_async = AsyncMock(return_value=MagicMock(data=[]))
        return builder

    sb.table = MagicMock(side_effect=table)
    with patch("app.config.get_settings", _settings), \
         patch("app.api.v2.routers.internal_calendar_intelligence.get_settings", _settings), \
         patch("app.api.v2.routers.internal_calendar_intelligence.get_supabase_admin_client", return_value=sb):
        resp = client.post(ENDPOINT, headers={"X-Internal-Secret": SECRET}, json=_body())
    assert resp.status_code == 400


def test_backfill_calls_service(client):
    svc = MagicMock()
    svc.backfill_recall_registrations = AsyncMock(return_value={"registered": 3})
    with patch("app.config.get_settings", _settings), \
         patch("app.api.v2.routers.internal_calendar_intelligence.get_settings", _settings), \
         patch("app.services.google_calendar_service.get_google_calendar_service", return_value=svc):
        resp = client.post(
            "/api/v2/internal/calendar-intelligence/backfill",
            headers={"X-Internal-Secret": SECRET}, json={},
        )
    assert resp.status_code == 200
    assert resp.json()["registered"] == 3
