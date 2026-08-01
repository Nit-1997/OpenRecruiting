"""Tests for POST /api/v2/intake/sessions/:id/switch?to=text|voice."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.modality_lock import ModalityConflictError
from app.services.voice_agent_client import VoiceAgentDrainError


def _make_session_mock(session_id):
    """Return a minimal IntakeSessionResponse-like mock that satisfies model_dump."""
    m = MagicMock()
    m.model_dump.return_value = {"id": str(session_id), "active_modality": "text"}
    return m

V2_ROOT = "/api/v2"


def test_switch_to_text_drains_voice_then_flips_lock(recruiter_client):
    sid = uuid4()
    with patch("app.api.v2.routers.intake_switch.VoiceAgentClient") as vc_cls, \
         patch("app.api.v2.routers.intake_switch.set_modality", new=AsyncMock()) as mock_set, \
         patch("app.api.v2.routers.intake_switch.IntakeSessionService") as svc_cls:
        vc = vc_cls.return_value
        vc.drain_session = AsyncMock(return_value={"drained": True})
        svc = svc_cls.return_value
        svc.get_session = AsyncMock(return_value=_make_session_mock(sid))
        resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions/{sid}/switch?to=text")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_modality"] == "text"
    vc.drain_session.assert_awaited_once()
    mock_set.assert_awaited_once()
    assert mock_set.call_args.kwargs["modality"] == "text"


def test_switch_to_voice_acquires_lock_returns_hint(recruiter_client):
    # The voice-switch path does an ownership check (get_session) then SETS the
    # modality lock to 'voice' unconditionally via set_modality (text mode is
    # stateless SSE — there is no live connection to drain), and returns a hint
    # telling the frontend to follow up with POST .../voice/start.
    sid = uuid4()
    with patch("app.api.v2.routers.intake_switch.set_modality", new=AsyncMock()) as mock_set, \
         patch("app.api.v2.routers.intake_switch.IntakeSessionService") as svc_cls:
        svc = svc_cls.return_value
        svc.get_session = AsyncMock(return_value=_make_session_mock(sid))
        resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions/{sid}/switch?to=voice")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_modality"] == "voice"
    assert body["next_step"] == "voice_start"
    mock_set.assert_awaited_once()
    assert mock_set.call_args.kwargs["modality"] == "voice"


def test_switch_to_voice_returns_409_when_lock_write_conflicts(recruiter_client):
    # BE-G2: a deterministic modality conflict on the lock write must surface as a
    # proper 409 (it used to be a generic 5xx). The route must NOT report success —
    # it does not return the voice_start hint. The conflict carries definite info
    # (held / requested) from the deterministic acquire RPC.
    sid = uuid4()
    with patch("app.api.v2.routers.intake_switch.set_modality", new=AsyncMock()) as mock_set, \
         patch("app.api.v2.routers.intake_switch.IntakeSessionService") as svc_cls:
        svc = svc_cls.return_value
        svc.get_session = AsyncMock(return_value=_make_session_mock(sid))
        mock_set.side_effect = ModalityConflictError(session_id=sid, held="text", requested="voice")
        resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions/{sid}/switch?to=voice")
    assert resp.status_code == 409
    body = resp.json()
    assert "active_modality" not in body
    assert body.get("held") == "text"


def test_switch_rejects_invalid_target(recruiter_client):
    sid = uuid4()
    resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions/{sid}/switch?to=carrier_pigeon")
    assert resp.status_code in (400, 422)


def test_switch_to_text_returns_502_if_drain_fails_hard(recruiter_client):
    sid = uuid4()
    with patch("app.api.v2.routers.intake_switch.VoiceAgentClient") as vc_cls, \
         patch("app.api.v2.routers.intake_switch.set_modality", new=AsyncMock()) as mock_set, \
         patch("app.api.v2.routers.intake_switch.IntakeSessionService") as svc_cls:
        vc = vc_cls.return_value
        vc.drain_session = AsyncMock(side_effect=VoiceAgentDrainError("server died"))
        svc = svc_cls.return_value
        svc.get_session = AsyncMock(return_value=_make_session_mock(sid))
        resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions/{sid}/switch?to=text")
    assert resp.status_code == 502
    mock_set.assert_not_awaited()


def test_switch_to_text_succeeds_when_already_idle(recruiter_client):
    sid = uuid4()
    with patch("app.api.v2.routers.intake_switch.VoiceAgentClient") as vc_cls, \
         patch("app.api.v2.routers.intake_switch.set_modality", new=AsyncMock()) as mock_set, \
         patch("app.api.v2.routers.intake_switch.IntakeSessionService") as svc_cls:
        vc = vc_cls.return_value
        vc.drain_session = AsyncMock(return_value={"drained": True, "already_idle": True})
        svc = svc_cls.return_value
        svc.get_session = AsyncMock(return_value=_make_session_mock(sid))
        resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions/{sid}/switch?to=text")
    assert resp.status_code == 200
    assert resp.json()["active_modality"] == "text"
    mock_set.assert_awaited_once()


def test_switch_to_text_cross_tenant_does_not_drain(recruiter_client):
    """Cross-tenant DoS guard: a session owned by another org must return 404
    and must NOT trigger the voice-agent drain endpoint."""
    sid = uuid4()
    with patch("app.api.v2.routers.intake_switch.VoiceAgentClient") as vc_cls, \
         patch("app.api.v2.routers.intake_switch.set_modality", new=AsyncMock()) as mock_set, \
         patch("app.api.v2.routers.intake_switch.IntakeSessionService") as svc_cls:
        vc = vc_cls.return_value
        vc.drain_session = AsyncMock(return_value={"drained": True})
        svc = svc_cls.return_value
        # Simulate a session_id that belongs to a different org/user
        svc.get_session = AsyncMock(side_effect=LookupError("Session not found"))
        resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions/{sid}/switch?to=text")

    assert resp.status_code == 404
    vc.drain_session.assert_not_awaited()
    mock_set.assert_not_awaited()


def _make_session_mock_with_modality(session_id, modality):
    """Return a minimal IntakeSessionResponse-like mock with a specific active_modality."""
    m = MagicMock()
    m.active_modality = modality
    m.model_dump.return_value = {"id": str(session_id), "active_modality": modality}
    return m


def test_switch_to_none_when_voice_active_drains_then_clears(recruiter_client):
    """to=none with active_modality='voice': ownership check -> drain -> clear lock."""
    sid = uuid4()
    with patch("app.api.v2.routers.intake_switch.VoiceAgentClient") as vc_cls, \
         patch("app.api.v2.routers.intake_switch.set_modality", new=AsyncMock()) as mock_set, \
         patch("app.api.v2.routers.intake_switch.IntakeSessionService") as svc_cls:
        vc = vc_cls.return_value
        vc.drain_session = AsyncMock(return_value={"drained": True})
        svc = svc_cls.return_value
        svc.get_session = AsyncMock(return_value=_make_session_mock_with_modality(sid, "voice"))
        resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions/{sid}/switch?to=none")

    assert resp.status_code == 200
    body = resp.json()
    assert body["active_modality"] is None
    vc.drain_session.assert_awaited_once()
    mock_set.assert_awaited_once()
    assert mock_set.call_args.kwargs["modality"] is None


def test_switch_to_none_when_text_active_clears_without_drain(recruiter_client):
    """to=none with active_modality='text': ownership check -> clear, NO drain."""
    sid = uuid4()
    with patch("app.api.v2.routers.intake_switch.VoiceAgentClient") as vc_cls, \
         patch("app.api.v2.routers.intake_switch.set_modality", new=AsyncMock()) as mock_set, \
         patch("app.api.v2.routers.intake_switch.IntakeSessionService") as svc_cls:
        vc = vc_cls.return_value
        vc.drain_session = AsyncMock(return_value={"drained": True})
        svc = svc_cls.return_value
        svc.get_session = AsyncMock(return_value=_make_session_mock_with_modality(sid, "text"))
        resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions/{sid}/switch?to=none")

    assert resp.status_code == 200
    body = resp.json()
    assert body["active_modality"] is None
    vc.drain_session.assert_not_awaited()
    mock_set.assert_awaited_once()
    assert mock_set.call_args.kwargs["modality"] is None


def test_switch_to_none_when_already_null_is_idempotent(recruiter_client):
    """to=none with active_modality=None: ownership check -> 200 idempotent, no drain, no DB write."""
    sid = uuid4()
    with patch("app.api.v2.routers.intake_switch.VoiceAgentClient") as vc_cls, \
         patch("app.api.v2.routers.intake_switch.set_modality", new=AsyncMock()) as mock_set, \
         patch("app.api.v2.routers.intake_switch.IntakeSessionService") as svc_cls:
        vc = vc_cls.return_value
        vc.drain_session = AsyncMock(return_value={"drained": True})
        svc = svc_cls.return_value
        svc.get_session = AsyncMock(return_value=_make_session_mock_with_modality(sid, None))
        resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions/{sid}/switch?to=none")

    assert resp.status_code == 200
    body = resp.json()
    assert body["active_modality"] is None
    vc.drain_session.assert_not_awaited()
    mock_set.assert_not_awaited()


def test_switch_to_none_cross_tenant_returns_404_no_drain(recruiter_client):
    """Cross-tenant DoS guard for to=none: 404 with no drain side-effect."""
    sid = uuid4()
    with patch("app.api.v2.routers.intake_switch.VoiceAgentClient") as vc_cls, \
         patch("app.api.v2.routers.intake_switch.set_modality", new=AsyncMock()) as mock_set, \
         patch("app.api.v2.routers.intake_switch.IntakeSessionService") as svc_cls:
        vc = vc_cls.return_value
        vc.drain_session = AsyncMock(return_value={"drained": True})
        svc = svc_cls.return_value
        svc.get_session = AsyncMock(side_effect=LookupError("Session not found"))
        resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions/{sid}/switch?to=none")

    assert resp.status_code == 404
    vc.drain_session.assert_not_awaited()
    mock_set.assert_not_awaited()


def test_switch_to_none_returns_502_when_voice_drain_fails(recruiter_client):
    """If drain fails on voice end-conversation: 502 and modality NOT cleared."""
    sid = uuid4()
    with patch("app.api.v2.routers.intake_switch.VoiceAgentClient") as vc_cls, \
         patch("app.api.v2.routers.intake_switch.set_modality", new=AsyncMock()) as mock_set, \
         patch("app.api.v2.routers.intake_switch.IntakeSessionService") as svc_cls:
        vc = vc_cls.return_value
        vc.drain_session = AsyncMock(side_effect=VoiceAgentDrainError("server died"))
        svc = svc_cls.return_value
        svc.get_session = AsyncMock(return_value=_make_session_mock_with_modality(sid, "voice"))
        resp = recruiter_client.post(f"{V2_ROOT}/intake/sessions/{sid}/switch?to=none")

    assert resp.status_code == 502
    mock_set.assert_not_awaited()
