"""
Tests for v2 intake session endpoints.

  POST /api/v2/intake/sessions      → 201 + session_id + requisition_id
  GET  /api/v2/intake/sessions/{id} → 200 + full session row

Service is patched at the router level — no Supabase HTTP calls fired.
Auth is overridden via the conftest recruiter_client fixture
(overrides get_current_user → CurrentUserWithOrg resolves from it).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from tests.helpers.mock_data import ORG_ID, RECRUITER_USER_ID, NOW


V2_ROOT = "/api/v2"

_FLAG_PATH = "app.api.v2.routers.intake_sessions.is_intake_v2_enabled"
SESSION_ID = "00000000-0000-0000-0000-0000000000b0"
REQ_ID_NEW = "00000000-0000-0000-0000-0000000000c0"

_VALID_FORM = {
    "role_name": "Senior Backend Engineer",
    "experience_min": 5,
    "experience_max": 8,
    "location": "NYC",
    "jd_text": None,
}

_VALID_PAYLOAD = {
    "form_data": _VALID_FORM,
    "entry_point": "create_role_btn",
}


# ---------------------------------------------------------------------------
# POST /api/v2/intake/sessions
# ---------------------------------------------------------------------------


def test_create_session_returns_201(recruiter_client):
    with patch(_FLAG_PATH, new=AsyncMock(return_value=True)), \
         patch("app.api.v2.routers.intake_sessions.IntakeSessionService") as svc_cls:
        svc = svc_cls.return_value
        svc.create_session = AsyncMock(return_value=MagicMock(
            session_id=UUID(SESSION_ID),
            requisition_id=UUID(REQ_ID_NEW),
            model_dump=lambda mode=None: {
                "session_id": SESSION_ID,
                "requisition_id": REQ_ID_NEW,
            },
        ))
        resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions", json=_VALID_PAYLOAD)

    assert resp.status_code == 201
    body = resp.json()
    assert body["session_id"] == SESSION_ID
    assert body["requisition_id"] == REQ_ID_NEW


def test_create_session_passes_correct_args(recruiter_client):
    with patch(_FLAG_PATH, new=AsyncMock(return_value=True)), \
         patch("app.api.v2.routers.intake_sessions.IntakeSessionService") as svc_cls:
        svc = svc_cls.return_value
        svc.create_session = AsyncMock(return_value=MagicMock(
            session_id=UUID(SESSION_ID),
            requisition_id=UUID(REQ_ID_NEW),
        ))
        recruiter_client.post(f"{V2_ROOT}/intake/sessions", json=_VALID_PAYLOAD)

    call_kwargs = svc.create_session.call_args.kwargs
    assert call_kwargs["org_id"] == UUID(ORG_ID)
    assert call_kwargs["entry_point"] == "create_role_btn"
    assert call_kwargs["form_data"].role_name == "Senior Backend Engineer"
    assert call_kwargs["requisition_id"] is None


def test_create_session_accepts_requisition_id_without_form(recruiter_client):
    """Complete-intake path: requisition_id alone is a valid payload — the
    service seeds form_data from the requisition row."""
    with patch(_FLAG_PATH, new=AsyncMock(return_value=True)), \
         patch("app.api.v2.routers.intake_sessions.IntakeSessionService") as svc_cls:
        svc = svc_cls.return_value
        svc.create_session = AsyncMock(return_value=MagicMock(
            session_id=UUID(SESSION_ID),
            requisition_id=UUID(REQ_ID_NEW),
            model_dump=lambda mode=None: {
                "session_id": SESSION_ID,
                "requisition_id": REQ_ID_NEW,
            },
        ))
        resp = recruiter_client.post(
            f"{V2_ROOT}/intake/sessions",
            json={"requisition_id": REQ_ID_NEW, "entry_point": "complete_intake_btn"},
        )

    assert resp.status_code == 201
    call_kwargs = svc.create_session.call_args.kwargs
    assert call_kwargs["requisition_id"] == UUID(REQ_ID_NEW)
    assert call_kwargs["form_data"] is None
    assert call_kwargs["entry_point"] == "complete_intake_btn"


def test_create_session_rejects_payload_without_form_or_requisition(recruiter_client):
    resp = recruiter_client.post(
        f"{V2_ROOT}/intake/sessions", json={"entry_point": None}
    )
    assert resp.status_code == 422


def test_create_session_validates_empty_role_name(recruiter_client):
    bad_payload = {
        "form_data": {**_VALID_FORM, "role_name": ""},
        "entry_point": None,
    }
    resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions", json=bad_payload)
    assert resp.status_code == 422


def test_create_session_validates_negative_experience(recruiter_client):
    bad_payload = {
        "form_data": {**_VALID_FORM, "experience_min": -1},
        "entry_point": None,
    }
    resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions", json=bad_payload)
    assert resp.status_code == 422


def test_create_session_returns_500_on_runtime_error(recruiter_client):
    with patch(_FLAG_PATH, new=AsyncMock(return_value=True)), \
         patch("app.api.v2.routers.intake_sessions.IntakeSessionService") as svc_cls:
        svc_cls.return_value.create_session = AsyncMock(side_effect=RuntimeError("DB insert failed"))
        resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions", json=_VALID_PAYLOAD)

    assert resp.status_code == 500
    assert "DB insert failed" in resp.json()["detail"]


def test_create_session_403_when_flag_disabled(recruiter_client):
    with patch(_FLAG_PATH, new=AsyncMock(return_value=False)):
        resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions", json=_VALID_PAYLOAD)

    assert resp.status_code == 403
    assert "not enabled" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/v2/intake/sessions/{session_id}
# ---------------------------------------------------------------------------


def _make_session_row():
    return {
        "id": SESSION_ID,
        "requisition_id": REQ_ID_NEW,
        "user_id": RECRUITER_USER_ID,
        "organization_id": ORG_ID,
        "status": "created",
        "active_modality": None,
        "entry_point": "create_role_btn",
        "form_data": _VALID_FORM,
        "questions_version": "1.0",
        "questions_snapshot": [],
        "prefilled_answers": None,
        "current_answers": None,
        "turns": [],
        "process_stages": [],
        "process_status": "idle",
        "process_error": None,
        "interview_plan": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


def test_get_session_returns_200(recruiter_client):
    from app.api.v2.schemas.intake import IntakeSessionResponse

    session_obj = IntakeSessionResponse(**_make_session_row())

    with patch("app.api.v2.routers.intake_sessions.IntakeSessionService") as svc_cls:
        svc_cls.return_value.get_session = AsyncMock(return_value=session_obj)
        resp = recruiter_client.get(f"{V2_ROOT}/intake/sessions/{SESSION_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == SESSION_ID
    assert body["status"] == "created"


def test_get_session_returns_404_when_not_found(recruiter_client):
    with patch("app.api.v2.routers.intake_sessions.IntakeSessionService") as svc_cls:
        svc_cls.return_value.get_session = AsyncMock(side_effect=LookupError("not found"))
        resp = recruiter_client.get(f"{V2_ROOT}/intake/sessions/{SESSION_ID}")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Session not found"


def test_create_session_requires_auth(unauthed_client):
    resp = unauthed_client.post(f"{V2_ROOT}/intake/sessions", json=_VALID_PAYLOAD)
    assert resp.status_code in (401, 403)


def test_get_session_requires_auth(unauthed_client):
    resp = unauthed_client.get(f"{V2_ROOT}/intake/sessions/{SESSION_ID}")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /api/v2/intake/sessions — list (B1.1)
# ---------------------------------------------------------------------------


def test_list_sessions_returns_200_with_array(recruiter_client):
    from app.api.v2.schemas.intake import ListSessionsResponse, SessionListItem
    from datetime import datetime, timezone
    from uuid import UUID, uuid4

    sid = uuid4()
    rid = uuid4()
    payload = ListSessionsResponse(sessions=[
        SessionListItem(
            session_id=sid,
            requisition_id=rid,
            title="Intake: Senior BE",
            display_status="incomplete",
            detail_status="created",
            last_activity_at=datetime.now(timezone.utc),
            active_modality=None,
            resume_url=f"/intake/sessions/{sid}",
            role_name="Senior BE",
            exp_min=5,
            exp_max=8,
            location="Remote · US",
        ),
    ])

    with patch("app.api.v2.routers.intake_sessions.IntakeSessionService") as svc_cls:
        svc_cls.return_value.list_user_sessions = AsyncMock(return_value=payload)
        resp = recruiter_client.get(f"{V2_ROOT}/intake/sessions")

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["sessions"], list)
    assert len(body["sessions"]) == 1
    assert body["sessions"][0]["session_id"] == str(sid)
    assert body["sessions"][0]["display_status"] == "incomplete"
    assert body["sessions"][0]["role_name"] == "Senior BE"
    assert body["sessions"][0]["exp_min"] == 5
    assert body["sessions"][0]["exp_max"] == 8
    assert body["sessions"][0]["location"] == "Remote · US"


def test_list_sessions_returns_empty_array(recruiter_client):
    from app.api.v2.schemas.intake import ListSessionsResponse

    with patch("app.api.v2.routers.intake_sessions.IntakeSessionService") as svc_cls:
        svc_cls.return_value.list_user_sessions = AsyncMock(return_value=ListSessionsResponse(sessions=[]))
        resp = recruiter_client.get(f"{V2_ROOT}/intake/sessions")

    assert resp.status_code == 200
    assert resp.json() == {"sessions": []}


def test_list_sessions_requires_auth(unauthed_client):
    resp = unauthed_client.get(f"{V2_ROOT}/intake/sessions")
    assert resp.status_code in (401, 403)
