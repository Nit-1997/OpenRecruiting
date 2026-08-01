"""Tests for POST /api/v2/webhooks/feedback-complete (the Lambda callback).

The callback is guarded by X-Lambda-Secret (conftest sets LAMBDA_CALLBACK_SECRET
= 'test-lambda-secret'). Covers: missing/invalid secret, happy path (emails +
SQS event), and the swallow-all error branch.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

ENDPOINT = "/api/v2/webhooks/feedback-complete"
SECRET = "test-lambda-secret"
CR_ID = "00000000-0000-0000-0000-0000000000bb"


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_invalid_secret_401(client):
    resp = client.post(ENDPOINT, headers={"X-Lambda-Secret": "wrong"}, json={"candidate_round_id": CR_ID})
    assert resp.status_code == 401


def test_missing_secret_401(client):
    resp = client.post(ENDPOINT, json={"candidate_round_id": CR_ID})
    assert resp.status_code == 401


def _notification_service():
    svc = MagicMock()
    svc.send_happy_path_emails = AsyncMock(return_value={"scheduler": True, "interviewer": False})
    return svc


def _supabase(org_id="org-1"):
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("select", "eq", "single"):
        setattr(builder, attr, MagicMock(return_value=builder))
    data = None
    if org_id is not None:
        data = {"id": CR_ID, "candidates": {"requisitions": {"organization_id": org_id}}}
    builder.execute_async = AsyncMock(return_value=MagicMock(data=data))
    sb.table = MagicMock(return_value=builder)
    return sb


def test_happy_path_sends_emails_and_publishes_event(client):
    notif = _notification_service()
    sb = _supabase("org-1")
    publish = AsyncMock()
    with patch("app.api.v2.routers.webhooks_feedback.get_feedback_notification_service", return_value=notif), \
         patch("app.api.v2.routers.webhooks_feedback.get_supabase_admin_client", return_value=sb), \
         patch("app.api.v2.routers.webhooks_feedback.publish_event", publish):
        resp = client.post(ENDPOINT, headers={"X-Lambda-Secret": SECRET}, json={"candidate_round_id": CR_ID})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["emails_sent"]["scheduler"] is True
    publish.assert_awaited_once()
    assert publish.call_args.args[0] == "feedback_complete"


def test_happy_path_no_org_skips_event(client):
    notif = _notification_service()
    sb = _supabase(org_id=None)  # no candidate_round row
    publish = AsyncMock()
    with patch("app.api.v2.routers.webhooks_feedback.get_feedback_notification_service", return_value=notif), \
         patch("app.api.v2.routers.webhooks_feedback.get_supabase_admin_client", return_value=sb), \
         patch("app.api.v2.routers.webhooks_feedback.publish_event", publish):
        resp = client.post(ENDPOINT, headers={"X-Lambda-Secret": SECRET}, json={"candidate_round_id": CR_ID})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    publish.assert_not_awaited()


def test_error_branch_returns_success_false(client):
    notif = MagicMock()
    notif.send_happy_path_emails = AsyncMock(side_effect=RuntimeError("email blew up"))
    with patch("app.api.v2.routers.webhooks_feedback.get_feedback_notification_service", return_value=notif):
        resp = client.post(ENDPOINT, headers={"X-Lambda-Secret": SECRET}, json={"candidate_round_id": CR_ID})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "email blew up" in body["error"]
