"""Tests for POST /api/v2/intake/sessions/:id/voice/start."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID

import httpx
import pytest

SESSION_ID = "00000000-0000-0000-0000-0000000000b0"
V2_ROOT = "/api/v2"


def test_voice_start_returns_answer(recruiter_client):
    with patch("app.api.v2.routers.voice.require_no_other_modality", new=AsyncMock()), \
         patch(
             "app.api.v2.routers.voice.request_voice_offer",
             new=AsyncMock(return_value={"sdp": "answer-sdp", "type": "answer"}),
         ):
        resp = recruiter_client.post(
            f"{V2_ROOT}/intake/sessions/{SESSION_ID}/voice/start",
            json={"sdp": "offer-sdp", "type": "offer"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sdp"] == "answer-sdp"
    assert body["type"] == "answer"


def test_voice_start_returns_409_on_modality_conflict(recruiter_client):
    with patch("app.api.v2.routers.voice.require_no_other_modality", new=AsyncMock()), \
         patch(
             "app.api.v2.routers.voice.request_voice_offer",
             new=AsyncMock(
                 side_effect=RuntimeError("voice agent rejected offer: modality conflict")
             ),
         ):
        resp = recruiter_client.post(
            f"{V2_ROOT}/intake/sessions/{SESSION_ID}/voice/start",
            json={"sdp": "x", "type": "offer"},
        )
    assert resp.status_code == 409


def test_voice_start_returns_404_when_session_not_found(recruiter_client):
    with patch(
        "app.api.v2.routers.voice.require_no_other_modality",
        new=AsyncMock(side_effect=LookupError("intake_sessions row not found")),
    ):
        resp = recruiter_client.post(
            f"{V2_ROOT}/intake/sessions/{SESSION_ID}/voice/start",
            json={"sdp": "x", "type": "offer"},
        )
    assert resp.status_code == 404
    assert "session not found" in resp.json()["detail"].lower()


def test_voice_start_returns_502_on_agent_unreachable(recruiter_client):
    with patch("app.api.v2.routers.voice.require_no_other_modality", new=AsyncMock()), \
         patch(
             "app.api.v2.routers.voice.request_voice_offer",
             new=AsyncMock(side_effect=httpx.ConnectError("connection refused")),
         ):
        resp = recruiter_client.post(
            f"{V2_ROOT}/intake/sessions/{SESSION_ID}/voice/start",
            json={"sdp": "x", "type": "offer"},
        )
    assert resp.status_code == 502
