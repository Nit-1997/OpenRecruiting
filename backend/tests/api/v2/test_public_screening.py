"""Behavioral coverage for the no-login candidate screening portal endpoints in
`app/api/v2/routers/public_screening.py`.

Mirrors `test_public_feedback_endpoints.py`. All Supabase / email IO is mocked via
respx + monkeypatch so the tests are deterministic and never touch the network.

The screening session JWT carries a DISTINCT `type="screening_session"`, so a
feedback-typed token must NOT satisfy the screening gate (and vice versa).
"""
from datetime import datetime, timezone, timedelta

import httpx

import app.api.v2.routers.public_screening as ps
from tests.helpers.mock_data import CANDIDATE_ROUND_ID, ROUND_ID
from tests.helpers.supabase_mocks import rest_url

V2_ROOT = "/api/v2/public/screening"
PATH_TOKEN = "test-screening-token-abc"
INVITE_ID = "00000000-0000-0000-0000-0000000000c0"


def _invite_record(**overrides):
    record = {
        "id": INVITE_ID,
        "token": PATH_TOKEN,
        "candidate_round_id": CANDIDATE_ROUND_ID,
        "candidate_email": "candidate@example.com",
        "otp_code": None,
        "otp_expires_at": None,
        "otp_attempts": 0,
        "otp_locked_until": None,
        "otp_last_sent_at": None,
        "otp_success_count": 0,
        "session_token": None,
        "session_expires_at": None,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "created_at": "2025-01-15T10:00:00+00:00",
        "updated_at": "2025-01-15T10:00:00+00:00",
        "last_accessed_at": None,
        "candidate_rounds": {
            "id": CANDIDATE_ROUND_ID,
            "screening_voice_session_status": None,
            "rounds": {
                "id": ROUND_ID,
                "name": "Screening",
                "requisitions": {"role_title": "Software Engineer"},
            },
        },
    }
    record.update(overrides)
    return record


def _mock_invite_lookup(respx_mock, record=None):
    respx_mock.get(rest_url("screening_invites")).mock(
        return_value=httpx.Response(200, json=[record or _invite_record()])
    )


def _valid_session_token(token_id=INVITE_ID):
    return ps.create_screening_session_token(
        token_id=token_id,
        candidate_email="candidate@example.com",
        candidate_round_id=CANDIDATE_ROUND_ID,
    )[0]


def _auth_header():
    return {"Authorization": f"Bearer {_valid_session_token()}"}


# ---------------------------------------------------------------------------
# GET /{token} — context (pre-auth)
# ---------------------------------------------------------------------------


def test_get_context_happy_path(unauthed_client, respx_mock):
    _mock_invite_lookup(respx_mock)
    resp = unauthed_client.get(f"{V2_ROOT}/{PATH_TOKEN}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["role_title"] == "Software Engineer"
    assert body["round_name"] == "Screening"
    assert body["email_hint"] == "c***@example.com"
    assert body["has_active_session"] is False
    # OTP / internal ids must never leak.
    assert "otp_code" not in body
    assert "candidate_round_id" not in body
    assert "id" not in body


def test_get_context_404_when_missing(unauthed_client, respx_mock):
    respx_mock.get(rest_url("screening_invites")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = unauthed_client.get(f"{V2_ROOT}/{PATH_TOKEN}")
    assert resp.status_code == 404


def test_expired_link_410_get(unauthed_client, respx_mock):
    record = _invite_record(expires_at="2000-01-01T00:00:00+00:00")
    _mock_invite_lookup(respx_mock, record)
    resp = unauthed_client.get(f"{V2_ROOT}/{PATH_TOKEN}")
    assert resp.status_code == 410
    assert "expired" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /{token}/send-otp
# ---------------------------------------------------------------------------


def test_send_otp_happy_path(unauthed_client, respx_mock, monkeypatch):
    record = _invite_record()
    _mock_invite_lookup(respx_mock, record)
    respx_mock.patch(rest_url("screening_invites")).mock(
        return_value=httpx.Response(200, json=[record])
    )

    sent = {}

    class _EmailResult:
        success = True
        error = None

    class _FakeEmailService:
        async def send_templated_email(self, **kwargs):
            sent.update(kwargs)
            return _EmailResult()

    monkeypatch.setattr(ps, "get_email_service", lambda: _FakeEmailService())

    resp = unauthed_client.post(f"{V2_ROOT}/{PATH_TOKEN}/send-otp")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["email_hint"] == "c***@example.com"
    assert sent["to_email"] == "candidate@example.com"
    assert sent["context"]["otp_code"].isdigit()


def test_send_otp_rate_limited(unauthed_client, respx_mock):
    record = _invite_record(otp_last_sent_at=datetime.now(timezone.utc).isoformat())
    _mock_invite_lookup(respx_mock, record)
    resp = unauthed_client.post(f"{V2_ROOT}/{PATH_TOKEN}/send-otp")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["retry_after_seconds"] == 60


def test_send_otp_410_when_expired(unauthed_client, respx_mock):
    record = _invite_record(expires_at="2000-01-01T00:00:00+00:00")
    _mock_invite_lookup(respx_mock, record)
    resp = unauthed_client.post(f"{V2_ROOT}/{PATH_TOKEN}/send-otp")
    assert resp.status_code == 410


# ---------------------------------------------------------------------------
# POST /{token}/verify-otp
# ---------------------------------------------------------------------------


def test_expired_link_410_verify(unauthed_client, respx_mock):
    record = _invite_record(expires_at="2000-01-01T00:00:00+00:00")
    _mock_invite_lookup(respx_mock, record)
    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/verify-otp", json={"otp": "123456"}
    )
    assert resp.status_code == 410


def test_verify_otp_success_mints_session(unauthed_client, respx_mock):
    future = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    record = _invite_record(otp_code="654321", otp_expires_at=future, otp_success_count=0)
    _mock_invite_lookup(respx_mock, record)
    respx_mock.patch(rest_url("screening_invites")).mock(
        return_value=httpx.Response(200, json=[record])
    )

    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/verify-otp", json={"otp": "654321"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["session_token"]
    payload = ps.verify_screening_session_token(body["session_token"])
    assert payload is not None
    assert payload["type"] == "screening_session"
    assert payload["token_id"] == INVITE_ID


def test_verify_otp_lockout(unauthed_client, respx_mock):
    """The 3rd consecutive wrong code locks the account (shared OTP state machine,
    here exercised end-to-end through the screening verify route)."""
    future = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    respx_mock.patch(rest_url("screening_invites")).mock(
        return_value=httpx.Response(200, json=[_invite_record()])
    )

    # Two GETs per verify call (gate read + post-failure refresh). The gate read
    # drives verify_otp's attempt counter; on the 3rd verify it reaches MAX and the
    # error message reflects the lock. We feed otp_attempts = prior failures so the
    # 3rd call sees attempts=2 -> increments to 3 -> locks.
    gets = {"n": 0}

    def _lookup(request):
        # Pair index: 0,1 -> first verify; 2,3 -> second; 4,5 -> third.
        prior_failures = gets["n"] // 2
        gets["n"] += 1
        rec = _invite_record(
            otp_code="000000",
            otp_expires_at=future,
            otp_attempts=prior_failures,
        )
        return httpx.Response(200, json=[rec])

    respx_mock.get(rest_url("screening_invites")).mock(side_effect=_lookup)

    last = None
    for _ in range(3):
        last = unauthed_client.post(
            f"{V2_ROOT}/{PATH_TOKEN}/verify-otp", json={"otp": "999999"}
        )

    assert last.status_code == 200
    body = last.json()
    assert body["success"] is False
    # The 3rd failure locks the account — surfaced in the OTP error message.
    assert "locked" in body["error"].lower()


# ---------------------------------------------------------------------------
# GET /{token}/session  (session-gated)
# ---------------------------------------------------------------------------


def test_session_happy_path(unauthed_client, respx_mock):
    _mock_invite_lookup(respx_mock)
    respx_mock.patch(rest_url("screening_invites")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = unauthed_client.get(
        f"{V2_ROOT}/{PATH_TOKEN}/session", headers=_auth_header()
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["role_title"] == "Software Engineer"


def test_session_401_without_token(unauthed_client, respx_mock):
    _mock_invite_lookup(respx_mock)
    resp = unauthed_client.get(f"{V2_ROOT}/{PATH_TOKEN}/session")
    assert resp.status_code == 401


def test_session_rejects_feedback_typed_jwt(unauthed_client, respx_mock):
    """A feedback-session JWT (wrong `type`) must NOT satisfy the screening gate."""
    from app.services.otp_service import get_otp_service

    _mock_invite_lookup(respx_mock)
    feedback_token, _ = get_otp_service().create_session_token(
        token_id=INVITE_ID,
        interviewer_email="candidate@example.com",
        candidate_round_id=CANDIDATE_ROUND_ID,
    )
    resp = unauthed_client.get(
        f"{V2_ROOT}/{PATH_TOKEN}/session",
        headers={"Authorization": f"Bearer {feedback_token}"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /{token}/start-voice  (session-gated, voice-enabled-gated)
# ---------------------------------------------------------------------------


def test_start_voice_requires_session(unauthed_client, respx_mock, monkeypatch):
    from app.config import get_settings

    _mock_invite_lookup(respx_mock)
    monkeypatch.setattr(get_settings(), "VOICE_ENABLED", True)
    resp = unauthed_client.post(f"{V2_ROOT}/{PATH_TOKEN}/start-voice", json={})
    assert resp.status_code in (401, 403)


def test_start_voice_503_when_disabled(unauthed_client, respx_mock, monkeypatch):
    from app.config import get_settings

    _mock_invite_lookup(respx_mock)
    monkeypatch.setattr(get_settings(), "VOICE_ENABLED", False)
    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/start-voice", json={}, headers=_auth_header()
    )
    assert resp.status_code == 503
    assert "not enabled" in resp.json()["detail"].lower()


def test_start_voice_mints_token(unauthed_client, respx_mock, monkeypatch):
    from app.config import get_settings

    _mock_invite_lookup(respx_mock)
    monkeypatch.setattr(get_settings(), "VOICE_ENABLED", True)

    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200, json=[{"screening_voice_session_status": None}]
        )
    )

    captured = {}

    def _patch(request):
        captured["body"] = request.content.decode()
        return httpx.Response(200, json=[{"id": CANDIDATE_ROUND_ID}])

    respx_mock.patch(rest_url("candidate_rounds")).mock(side_effect=_patch)

    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/start-voice", json={}, headers=_auth_header()
    )
    assert resp.status_code == 200
    assert resp.json()["voice_session_token"]
    # Assert the CAS update payload sets status pending + a token.
    assert '"screening_voice_session_status":"pending"' in captured["body"].replace(" ", "")
    assert "screening_voice_session_token" in captured["body"]


def test_start_voice_409_on_lost_race(unauthed_client, respx_mock, monkeypatch):
    from app.config import get_settings

    _mock_invite_lookup(respx_mock)
    monkeypatch.setattr(get_settings(), "VOICE_ENABLED", True)

    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200, json=[{"screening_voice_session_status": "pending"}]
        )
    )
    # Conditional mint affects ZERO rows (concurrent caller changed status).
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )

    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/start-voice",
        json={"redo": True},
        headers=_auth_header(),
    )
    assert resp.status_code == 409
