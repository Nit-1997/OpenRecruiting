"""Tests for POST /api/v2/intake/sessions/:id/text/messages SSE endpoint."""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.v2.core.dependencies import get_supabase, get_current_user_with_org, CurrentUserWithOrg
from app.dependencies import CurrentUser
from tests.helpers.mock_data import ORG_ID, RECRUITER_USER_ID, RECRUITER_EMAIL


V2_ROOT = "/api/v2"

RECRUITER_USER = CurrentUser(
    id=UUID(RECRUITER_USER_ID),
    email=RECRUITER_EMAIL,
    is_staff=False,
    organization_id=UUID(ORG_ID),
)
RECRUITER_WITH_ORG = CurrentUserWithOrg(
    user=RECRUITER_USER,
    organization_id=UUID(ORG_ID),
)


def _parse_sse(body: str) -> list[dict]:
    """Parse SSE wire format into a list of {event, data} dicts."""
    out = []
    cur_event = "message"
    cur_data_lines: list[str] = []
    for line in body.split("\n"):
        if line == "":
            if cur_data_lines:
                data_str = "\n".join(cur_data_lines)
                out.append({"event": cur_event, "data": data_str})
                cur_event = "message"
                cur_data_lines = []
            continue
        if line.startswith("event: "):
            cur_event = line[len("event: "):]
        elif line.startswith("data: "):
            cur_data_lines.append(line[len("data: "):])
    return out


def test_text_messages_streams_sse_chunks(recruiter_client):
    session_id = uuid4()

    async def fake_gen(**kwargs):
        yield ("text", "Hello ")
        yield ("text", "world")
        yield ("done", {"text": "Hello world", "stop_reason": "end_turn",
                        "user_turn_idx": 0, "assistant_turn_idx": 1})

    mock_supabase = MagicMock()
    # Pre-flight: aload_session() awaits `.execute_async()`, so it must be an
    # AsyncMock resolving to a row-bearing object. (The sync `.execute` was a
    # stale v1-era mock — the v2 route awaits the async path.)
    mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute_async = AsyncMock(
        return_value=MagicMock(
            data={
                "id": str(session_id),
                "active_modality": None,
                "status": "ready",
                "user_id": RECRUITER_USER_ID,
                "organization_id": ORG_ID,
            }
        )
    )

    with patch("app.api.v2.routers.intake_text_messages.require_no_other_modality", new=AsyncMock()), \
         patch("app.api.v2.routers.intake_text_messages.run_text_turn", new=fake_gen), \
         patch("app.api.v2.routers.intake_text_messages.get_anthropic_async_client",
               return_value=MagicMock()):
        app.dependency_overrides[get_supabase] = lambda: mock_supabase
        try:
            resp = recruiter_client.post(
                f"{V2_ROOT}/intake/sessions/{session_id}/text/messages",
                json={"message": "hi"},
            )
        finally:
            app.dependency_overrides.pop(get_supabase, None)

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    events = _parse_sse(resp.text)
    text_events = [json.loads(e["data"]) for e in events if e["event"] == "text"]
    assert text_events == ["Hello ", "world"]
    done_events = [json.loads(e["data"]) for e in events if e["event"] == "done"]
    assert len(done_events) == 1
    assert done_events[0]["assistant_turn_idx"] == 1


def test_text_messages_returns_409_on_modality_conflict(recruiter_client):
    session_id = uuid4()
    from app.services.modality_lock import ModalityConflictError as _LockConflict

    mock_supabase = MagicMock()

    with patch(
        "app.api.v2.routers.intake_text_messages.require_no_other_modality",
        new=AsyncMock(side_effect=_LockConflict(session_id=session_id, held="voice", requested="text")),
    ), patch("app.api.v2.routers.intake_text_messages.get_anthropic_async_client",
             return_value=MagicMock()):
        app.dependency_overrides[get_supabase] = lambda: mock_supabase
        try:
            resp = recruiter_client.post(
                f"{V2_ROOT}/intake/sessions/{session_id}/text/messages",
                json={"message": "hi"},
            )
        finally:
            app.dependency_overrides.pop(get_supabase, None)

    assert resp.status_code == 409
    body = resp.json()
    assert "voice" in body["held"].lower()


def test_text_messages_returns_404_when_session_not_found(recruiter_client):
    session_id = uuid4()

    mock_supabase = MagicMock()

    with patch(
        "app.api.v2.routers.intake_text_messages.require_no_other_modality",
        new=AsyncMock(side_effect=LookupError("intake_sessions row not found")),
    ), patch("app.api.v2.routers.intake_text_messages.get_anthropic_async_client",
             return_value=MagicMock()):
        app.dependency_overrides[get_supabase] = lambda: mock_supabase
        try:
            resp = recruiter_client.post(
                f"{V2_ROOT}/intake/sessions/{session_id}/text/messages",
                json={"message": "hi"},
            )
        finally:
            app.dependency_overrides.pop(get_supabase, None)

    assert resp.status_code == 404
    assert "session not found" in resp.json()["detail"].lower()


def test_text_messages_validates_message_non_empty(recruiter_client):
    session_id = uuid4()

    mock_supabase = MagicMock()

    with patch("app.api.v2.routers.intake_text_messages.require_no_other_modality", new=AsyncMock()), \
         patch("app.api.v2.routers.intake_text_messages.get_anthropic_async_client",
               return_value=MagicMock()):
        app.dependency_overrides[get_supabase] = lambda: mock_supabase
        try:
            resp = recruiter_client.post(
                f"{V2_ROOT}/intake/sessions/{session_id}/text/messages",
                json={"message": "  "},
            )
        finally:
            app.dependency_overrides.pop(get_supabase, None)

    assert resp.status_code == 422
