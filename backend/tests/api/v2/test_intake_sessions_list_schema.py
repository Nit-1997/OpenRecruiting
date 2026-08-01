"""Schema tests for SessionListItem + ListSessionsResponse."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError


def test_session_list_item_accepts_minimal_row():
    from app.api.v2.schemas.intake import SessionListItem

    item = SessionListItem(
        session_id=uuid4(),
        requisition_id=uuid4(),
        title="Intake: Senior Backend Engineer",
        display_status="incomplete",
        detail_status="created",
        last_activity_at=datetime.now(timezone.utc),
        active_modality=None,
        resume_url="/intake/sessions/abc",
    )
    assert item.display_status == "incomplete"
    assert item.active_modality is None


def test_session_list_item_rejects_bad_display_status():
    from app.api.v2.schemas.intake import SessionListItem

    with pytest.raises(ValidationError):
        SessionListItem(
            session_id=uuid4(),
            requisition_id=uuid4(),
            title="x",
            display_status="bogus",  # only incomplete | submitted | completed
            detail_status="created",
            last_activity_at=datetime.now(timezone.utc),
            active_modality=None,
            resume_url="/intake/sessions/abc",
        )


def test_list_sessions_response_wraps_array():
    from app.api.v2.schemas.intake import ListSessionsResponse, SessionListItem

    resp = ListSessionsResponse(sessions=[
        SessionListItem(
            session_id=uuid4(),
            requisition_id=uuid4(),
            title="Intake: x",
            display_status="completed",
            detail_status="published",
            last_activity_at=datetime.now(timezone.utc),
            active_modality="voice",
            resume_url="/intake/sessions/x",
        ),
    ])
    assert len(resp.sessions) == 1
    assert resp.sessions[0].active_modality == "voice"


def test_session_list_item_rich_fields_populated():
    from app.api.v2.schemas.intake import SessionListItem

    item = SessionListItem(
        session_id=uuid4(),
        requisition_id=uuid4(),
        title="Intake: Senior Backend Engineer",
        display_status="incomplete",
        detail_status="created",
        last_activity_at=datetime.now(timezone.utc),
        active_modality=None,
        resume_url="/intake/sessions/abc",
        role_name="Senior Backend Engineer",
        exp_min=5,
        exp_max=8,
        location="Remote · US",
    )
    assert item.role_name == "Senior Backend Engineer"
    assert item.exp_min == 5
    assert item.exp_max == 8
    assert item.location == "Remote · US"


def test_session_list_item_rich_fields_default_none():
    from app.api.v2.schemas.intake import SessionListItem

    item = SessionListItem(
        session_id=uuid4(),
        requisition_id=uuid4(),
        title="Intake: Senior Backend Engineer",
        display_status="incomplete",
        detail_status="created",
        last_activity_at=datetime.now(timezone.utc),
        active_modality=None,
        resume_url="/intake/sessions/abc",
    )
    assert item.role_name is None
    assert item.exp_min is None
    assert item.exp_max is None
    assert item.location is None
