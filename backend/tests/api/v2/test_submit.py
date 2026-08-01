"""Tests for POST /api/v2/intake/sessions/:id/submit and /api/v2/intake/sessions/:id/publish."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.intake_submit_service import IntakeSubmitError
from app.services.intake_publish_service import IntakePublishError

V2_ROOT = "/api/v2"


def test_submit_returns_202(recruiter_client):
    sid = uuid4()
    with patch("app.api.v2.routers.intake_submit.IntakeSubmitService") as svc_cls:
        svc = svc_cls.return_value
        svc.submit = AsyncMock(return_value={"session_id": str(sid), "status": "submitted"})
        resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions/{sid}/submit")
    assert resp.status_code == 202
    body = resp.json()
    assert body["session_id"] == str(sid)
    assert body["status"] == "submitted"


def test_submit_409_when_already_submitted(recruiter_client):
    sid = uuid4()
    with patch("app.api.v2.routers.intake_submit.IntakeSubmitService") as svc_cls:
        svc = svc_cls.return_value
        svc.submit = AsyncMock(side_effect=IntakeSubmitError("Session already submitted", status_code=409))
        resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions/{sid}/submit")
    assert resp.status_code == 409


def test_publish_returns_200_with_redirect_url(recruiter_client):
    sid, rid = uuid4(), uuid4()
    with patch("app.api.v2.routers.intake_submit.IntakePublishService") as svc_cls:
        svc = svc_cls.return_value
        # publish is now async — use AsyncMock so the router can await it
        svc.publish = AsyncMock(return_value={
            "session_id": str(sid),
            "requisition_id": str(rid),
            "redirect_url": f"/roles/{rid}",
        })
        resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions/{sid}/publish", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["redirect_url"] == f"/roles/{rid}"


def test_publish_with_edited_plan_forwards_to_service(recruiter_client):
    sid, rid = uuid4(), uuid4()
    edited = {"rounds": [{"name": "Edited", "category": "coding",
                          "skills": ["x"], "feedback_questions": [{"heading": "x", "description": "y"}]}]}
    with patch("app.api.v2.routers.intake_submit.IntakePublishService") as svc_cls:
        svc = svc_cls.return_value
        svc.publish = AsyncMock(return_value={
            "session_id": str(sid),
            "requisition_id": str(rid),
            "redirect_url": f"/roles/{rid}",
        })
        resp = recruiter_client.post(
            f"{V2_ROOT}/intake/sessions/{sid}/publish",
            json={"interview_plan": edited},
        )
    assert resp.status_code == 200
    svc.publish.assert_called_once()
    assert svc.publish.call_args.kwargs["edited_plan"] == edited


def test_publish_404_when_session_not_found(recruiter_client):
    sid = uuid4()
    with patch("app.api.v2.routers.intake_submit.IntakePublishService") as svc_cls:
        svc = svc_cls.return_value
        svc.publish = AsyncMock(side_effect=IntakePublishError("Session not found", status_code=404))
        resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions/{sid}/publish", json={})
    assert resp.status_code == 404


def test_publish_409_when_not_submitted(recruiter_client):
    sid = uuid4()
    with patch("app.api.v2.routers.intake_submit.IntakePublishService") as svc_cls:
        svc = svc_cls.return_value
        svc.publish = AsyncMock(side_effect=IntakePublishError("Session is not submitted", status_code=409))
        resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions/{sid}/publish", json={})
    assert resp.status_code == 409
