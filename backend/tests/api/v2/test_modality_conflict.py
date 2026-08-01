"""Tests for 409 Conflict when starting voice while text is active and vice versa."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.modality_lock import ModalityConflictError

V2_ROOT = "/api/v2"


def test_voice_start_returns_409_when_text_holds(recruiter_client):
    sid = uuid4()
    with patch(
        "app.api.v2.routers.voice.require_no_other_modality",
        new=AsyncMock(side_effect=ModalityConflictError(session_id=sid, held="text", requested="voice")),
    ):
        resp = recruiter_client.post(
            f"{V2_ROOT}/intake/sessions/{sid}/voice/start",
            json={"sdp": "offer-sdp", "type": "offer"},
        )
    assert resp.status_code == 409
    body = resp.json()
    assert "another mode" in body["detail"].lower()
    assert body.get("held") == "text"


def test_text_messages_returns_409_when_voice_holds(recruiter_client):
    sid = uuid4()
    with patch(
        "app.api.v2.routers.intake_text_messages.require_no_other_modality",
        new=AsyncMock(side_effect=ModalityConflictError(session_id=sid, held="voice", requested="text")),
    ):
        resp = recruiter_client.post(
            f"{V2_ROOT}/intake/sessions/{sid}/text/messages",
            json={"message": "hi"},
        )
    assert resp.status_code == 409
    assert resp.json().get("held") == "voice"
