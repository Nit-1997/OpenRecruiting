"""Behavioral coverage for the no-login feedback portal endpoints in
`app/api/v2/routers/public_feedback.py`.

The session-JWT gate itself is exercised in `test_public_feedback_session_gate.py`;
this file covers the *handlers* behind that gate (session/start-voice/edit/approve/
reprocess) plus the pre-auth endpoints (context/send-otp/verify-otp/openrecruiting-auth/
validate-session) and the `mask_email`/`is_significant_change` pure helpers.

All Supabase / email / feedback-Lambda IO is mocked via respx + monkeypatch so the
tests are deterministic and never touch the network.
"""
import httpx
import pytest

import app.api.v2.routers.public_feedback as pf
from app.services.otp_service import get_otp_service
from tests.helpers.mock_data import (
    FEEDBACK_TOKEN_ID,
    CANDIDATE_ROUND_ID,
    ROUND_ID,
    make_feedback_access_token,
)
from tests.helpers.supabase_mocks import rest_url

V2_ROOT = "/api/v2/public/feedback"
PATH_TOKEN = "test-feedback-token-abc"


def _token_record_with_join(**overrides):
    record = make_feedback_access_token()
    record["candidate_round_id"] = CANDIDATE_ROUND_ID
    record["candidate_rounds"] = {
        "id": CANDIDATE_ROUND_ID,
        "scheduled_at": None,
        "status": "completed",
        "summary": None,
        "rating": None,
        "scorecard_transcript": None,
        "interviewer_email": "interviewer@test.com",
        "candidates": {
            "id": "00000000-0000-0000-0000-000000000040",
            "name": "John Doe",
            "email": "john@example.com",
            "requisition_id": "00000000-0000-0000-0000-000000000020",
        },
        "rounds": {
            "id": ROUND_ID,
            "name": "Technical",
            "round_type": "interview",
        },
    }
    record.update(overrides)
    return record


def _valid_session_token(token_id=FEEDBACK_TOKEN_ID):
    otp_service = get_otp_service()
    session_token, _ = otp_service.create_session_token(
        token_id=token_id,
        interviewer_email="interviewer@test.com",
        candidate_round_id=CANDIDATE_ROUND_ID,
    )
    return session_token


def _mock_token_lookup(respx_mock, record=None):
    respx_mock.get(rest_url("feedback_access_tokens")).mock(
        return_value=httpx.Response(200, json=[record or _token_record_with_join()])
    )


def _auth_header():
    return {"Authorization": f"Bearer {_valid_session_token()}"}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "email,expected",
    [
        ("", "***@***"),
        ("no-at-sign", "***@***"),
        ("a@b.com", "*@b.com"),
        ("ab@x.io", "a***@x.io"),
        ("longlocal@dom.com", "l***@dom.com"),
    ],
)
def test_mask_email(email, expected):
    assert pf.mask_email(email) == expected


def test_is_significant_change_no_original_short():
    assert pf.is_significant_change("", "one line") is False


def test_is_significant_change_no_original_many_lines():
    big = "\n".join(["line"] * 25)
    assert pf.is_significant_change("", big) is True


def test_is_significant_change_many_added_lines():
    original = "a\nb"
    updated = original + "\n" + "\n".join(["x"] * 25)
    assert pf.is_significant_change(original, updated) is True


def test_is_significant_change_low_similarity():
    assert pf.is_significant_change("the quick brown fox", "ZZZ totally different YYY") is True


def test_is_significant_change_minor_edit_not_significant():
    assert pf.is_significant_change("hello world here", "hello world here!") is False


# ---------------------------------------------------------------------------
# GET /{token} — context (pre-auth)
# ---------------------------------------------------------------------------


def test_get_context_requires_otp_for_external_interviewer(unauthed_client, respx_mock):
    # is_registered_user already known (False) so no profile lookup / no update needed,
    # but the handler still persists is_registered_user when it was None. Here it's set,
    # and the email is already in sync, so only the token lookup fires.
    record = _token_record_with_join(is_registered_user=False)
    _mock_token_lookup(respx_mock, record)

    resp = unauthed_client.get(f"{V2_ROOT}/{PATH_TOKEN}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["requires_otp"] is True
    assert body["requires_platform_login"] is False
    assert body["has_active_session"] is False
    assert body["candidate_name"] == "John Doe"
    assert body["round_name"] == "Technical"
    assert body["email_hint"] == "i***@test.com"


def test_get_context_resolves_unknown_registered_user_and_persists(unauthed_client, respx_mock, monkeypatch):
    record = _token_record_with_join(is_registered_user=None)
    _mock_token_lookup(respx_mock, record)
    # is_registered_user is None -> handler calls otp_service.is_interviewer_registered
    # then PATCHes the token row.
    respx_mock.patch(rest_url("feedback_access_tokens")).mock(
        return_value=httpx.Response(200, json=[record])
    )

    async def _fake_registered(email):
        return True

    monkeypatch.setattr(get_otp_service(), "is_interviewer_registered", _fake_registered)

    resp = unauthed_client.get(f"{V2_ROOT}/{PATH_TOKEN}")

    assert resp.status_code == 200
    body = resp.json()
    # Registered OpenRecruiting user, no active session -> requires_platform_login.
    assert body["requires_platform_login"] is True
    assert body["requires_otp"] is False
    assert body["email_hint"] is None


def test_get_context_404_when_token_missing(unauthed_client, respx_mock):
    respx_mock.get(rest_url("feedback_access_tokens")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = unauthed_client.get(f"{V2_ROOT}/{PATH_TOKEN}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Invalid or expired feedback link"


def test_get_context_410_when_expired(unauthed_client, respx_mock):
    record = _token_record_with_join(expires_at="2000-01-01T00:00:00+00:00")
    _mock_token_lookup(respx_mock, record)
    resp = unauthed_client.get(f"{V2_ROOT}/{PATH_TOKEN}")
    assert resp.status_code == 410
    assert "expired" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /{token}/send-otp
# ---------------------------------------------------------------------------


def test_send_otp_blocks_registered_user(unauthed_client, respx_mock):
    record = _token_record_with_join(is_registered_user=True)
    _mock_token_lookup(respx_mock, record)

    resp = unauthed_client.post(f"{V2_ROOT}/{PATH_TOKEN}/send-otp")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "OpenRecruiting account" in body["message"]


def test_send_otp_happy_path_sends_email(unauthed_client, respx_mock, monkeypatch):
    record = _token_record_with_join(is_registered_user=False)
    _mock_token_lookup(respx_mock, record)
    respx_mock.patch(rest_url("feedback_access_tokens")).mock(
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

    monkeypatch.setattr(pf, "get_email_service", lambda: _FakeEmailService())

    resp = unauthed_client.post(f"{V2_ROOT}/{PATH_TOKEN}/send-otp")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["email_hint"] == "i***@test.com"
    assert sent["to_email"] == "interviewer@test.com"
    # OTP code is a 6-digit string passed in context.
    assert sent["context"]["otp_code"].isdigit()


def test_send_otp_email_failure_returns_unsuccessful(unauthed_client, respx_mock, monkeypatch):
    record = _token_record_with_join(is_registered_user=False)
    _mock_token_lookup(respx_mock, record)
    respx_mock.patch(rest_url("feedback_access_tokens")).mock(
        return_value=httpx.Response(200, json=[record])
    )

    class _EmailResult:
        success = False
        error = "smtp down"

    class _FakeEmailService:
        async def send_templated_email(self, **kwargs):
            return _EmailResult()

    monkeypatch.setattr(pf, "get_email_service", lambda: _FakeEmailService())

    resp = unauthed_client.post(f"{V2_ROOT}/{PATH_TOKEN}/send-otp")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "Failed to send" in body["message"]


def test_send_otp_rate_limited(unauthed_client, respx_mock):
    # otp_last_sent_at moments ago -> can_send_otp returns False (rate limited).
    from datetime import datetime, timezone

    record = _token_record_with_join(
        is_registered_user=False,
        otp_last_sent_at=datetime.now(timezone.utc).isoformat(),
    )
    _mock_token_lookup(respx_mock, record)

    resp = unauthed_client.post(f"{V2_ROOT}/{PATH_TOKEN}/send-otp")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["retry_after_seconds"] == 60


def test_send_otp_locked(unauthed_client, respx_mock):
    from datetime import datetime, timezone, timedelta

    locked_until = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    record = _token_record_with_join(is_registered_user=False, otp_locked_until=locked_until)
    _mock_token_lookup(respx_mock, record)

    resp = unauthed_client.post(f"{V2_ROOT}/{PATH_TOKEN}/send-otp")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "Too many failed attempts" in body["message"]


# ---------------------------------------------------------------------------
# POST /{token}/verify-otp
# ---------------------------------------------------------------------------


def test_verify_otp_blocks_registered_user(unauthed_client, respx_mock):
    record = _token_record_with_join(is_registered_user=True)
    _mock_token_lookup(respx_mock, record)

    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/verify-otp", json={"otp": "123456"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "OpenRecruiting account" in body["error"]


def test_verify_otp_success_returns_session_token(unauthed_client, respx_mock):
    from datetime import datetime, timezone, timedelta

    future = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    record = _token_record_with_join(
        is_registered_user=False,
        otp_code="654321",
        otp_expires_at=future,
        otp_success_count=0,
    )
    _mock_token_lookup(respx_mock, record)
    respx_mock.patch(rest_url("feedback_access_tokens")).mock(
        return_value=httpx.Response(200, json=[record])
    )

    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/verify-otp", json={"otp": "654321"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["session_token"]
    # The returned token must verify back to this feedback link.
    payload = get_otp_service().verify_session_token(body["session_token"])
    assert payload["token_id"] == FEEDBACK_TOKEN_ID


def test_verify_otp_wrong_code_returns_attempts_remaining(unauthed_client, respx_mock):
    from datetime import datetime, timezone, timedelta

    future = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    record = _token_record_with_join(
        is_registered_user=False,
        otp_code="000000",
        otp_expires_at=future,
        otp_attempts=0,
    )
    # Both the gate lookup and the post-failure refresh return the same record.
    _mock_token_lookup(respx_mock, record)
    respx_mock.patch(rest_url("feedback_access_tokens")).mock(
        return_value=httpx.Response(200, json=[record])
    )

    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/verify-otp", json={"otp": "999999"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["error"] is not None
    assert body["attempts_remaining"] is not None


# ---------------------------------------------------------------------------
# POST /{token}/openrecruiting-auth
# ---------------------------------------------------------------------------


def test_platform_auth_401_without_bearer(unauthed_client, respx_mock):
    _mock_token_lookup(respx_mock)
    resp = unauthed_client.post(f"{V2_ROOT}/{PATH_TOKEN}/openrecruiting-auth")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Supabase authorization required"


def test_platform_auth_success_for_matching_email(unauthed_client, respx_mock):
    import jwt as _jwt
    from app.config import get_settings

    record = _token_record_with_join(is_registered_user=True)
    _mock_token_lookup(respx_mock, record)
    respx_mock.patch(rest_url("feedback_access_tokens")).mock(
        return_value=httpx.Response(200, json=[record])
    )

    # Mint an HS256 supabase-style token whose email matches the interviewer.
    secret = get_settings().SUPABASE_JWT_SECRET
    supa_token = _jwt.encode(
        {"email": "interviewer@test.com", "aud": "authenticated"},
        secret,
        algorithm="HS256",
    )

    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/openrecruiting-auth",
        headers={"Authorization": f"Bearer {supa_token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["session_token"]


def test_platform_auth_403_for_mismatched_email(unauthed_client, respx_mock):
    import jwt as _jwt
    from app.config import get_settings

    record = _token_record_with_join(is_registered_user=True)
    _mock_token_lookup(respx_mock, record)

    secret = get_settings().SUPABASE_JWT_SECRET
    supa_token = _jwt.encode(
        {"email": "someone-else@test.com", "aud": "authenticated"},
        secret,
        algorithm="HS256",
    )

    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/openrecruiting-auth",
        headers={"Authorization": f"Bearer {supa_token}"},
    )

    assert resp.status_code == 403
    assert "does not match" in resp.json()["detail"]


def test_platform_auth_401_on_invalid_token(unauthed_client, respx_mock):
    record = _token_record_with_join(is_registered_user=True)
    _mock_token_lookup(respx_mock, record)

    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/openrecruiting-auth",
        headers={"Authorization": "Bearer not.a.jwt"},
    )

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /{token}/session  (session-gated)
# ---------------------------------------------------------------------------


def test_session_happy_path_returns_round_info_and_questions(unauthed_client, respx_mock):
    _mock_token_lookup(respx_mock)
    # /session PATCHes last_accessed_at, then reads feedback_questions for the round.
    respx_mock.patch(rest_url("feedback_access_tokens")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.get(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"question_number": 1, "heading": "Problem Solving", "description": "How"},
            ],
        )
    )

    resp = unauthed_client.get(
        f"{V2_ROOT}/{PATH_TOKEN}/session", headers=_auth_header()
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["candidate_name"] == "John Doe"
    assert body["round_name"] == "Technical"
    assert body["questions"][0]["heading"] == "Problem Solving"


# ---------------------------------------------------------------------------
# POST /{token}/start-voice  (session-gated, voice-enabled-gated)
# ---------------------------------------------------------------------------


def test_start_voice_503_when_voice_disabled(unauthed_client, respx_mock, monkeypatch):
    from app.config import get_settings

    _mock_token_lookup(respx_mock)
    # require_voice_enabled fires before the session gate; force VOICE_ENABLED off.
    settings = get_settings()
    monkeypatch.setattr(settings, "VOICE_ENABLED", False)

    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/start-voice", json={}, headers=_auth_header()
    )

    assert resp.status_code == 503
    assert "not enabled" in resp.json()["detail"]


def test_start_voice_mints_token_when_dormant(unauthed_client, respx_mock, monkeypatch):
    from app.config import get_settings

    _mock_token_lookup(respx_mock)
    monkeypatch.setattr(get_settings(), "VOICE_ENABLED", True)

    # First select: existing status is None.
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200, json=[{"feedback_voice_session_status": None}]
        )
    )
    # The conditional mint PATCH returns the updated row (affected > 0 rows).
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[{"id": CANDIDATE_ROUND_ID}])
    )

    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/start-voice", json={}, headers=_auth_header()
    )

    assert resp.status_code == 200
    assert resp.json()["voice_session_token"]


def test_start_voice_409_when_already_active_without_redo(unauthed_client, respx_mock, monkeypatch):
    from app.config import get_settings

    _mock_token_lookup(respx_mock)
    monkeypatch.setattr(get_settings(), "VOICE_ENABLED", True)

    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200, json=[{"feedback_voice_session_status": "active"}]
        )
    )

    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/start-voice", json={"redo": False}, headers=_auth_header()
    )

    assert resp.status_code == 409
    assert "already active" in resp.json()["detail"]


def test_start_voice_409_when_mint_loses_race(unauthed_client, respx_mock, monkeypatch):
    from app.config import get_settings

    _mock_token_lookup(respx_mock)
    monkeypatch.setattr(get_settings(), "VOICE_ENABLED", True)

    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200, json=[{"feedback_voice_session_status": "pending"}]
        )
    )
    # Conditional mint affected ZERO rows (a concurrent caller changed status).
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )

    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/start-voice", json={"redo": True}, headers=_auth_header()
    )

    assert resp.status_code == 409
    assert "same time" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /{token}/review  (session-gated) — exercised more fully than the gate test
# ---------------------------------------------------------------------------


def test_review_404_when_round_missing(unauthed_client, respx_mock):
    _mock_token_lookup(respx_mock)
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )

    resp = unauthed_client.get(
        f"{V2_ROOT}/{PATH_TOKEN}/review", headers=_auth_header()
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Candidate round not found"


def test_review_maps_question_summaries(unauthed_client, respx_mock):
    _mock_token_lookup(respx_mock)
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": CANDIDATE_ROUND_ID,
                "summary": "Great",
                "rating": "yes",
                "question_summaries": {"1": "Solid answer"},
                "processing_status": "completed",
                "scheduled_at": None,
                "round_id": ROUND_ID,
                "feedback_approved_at": "2025-01-15T10:00:00+00:00",
                "feedback_approved_by_email": "interviewer@test.com",
                "feedback_voice_session_status": "completed",
                "feedback_voice_session_error": None,
            }],
        )
    )
    respx_mock.get(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "q1", "question_number": 1, "heading": "Q1", "description": "d"}],
        )
    )

    resp = unauthed_client.get(
        f"{V2_ROOT}/{PATH_TOKEN}/review", headers=_auth_header()
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["is_approved"] is True
    assert body["question_summaries"][0]["summary"] == "Solid answer"
    assert body["feedback_voice_session_status"] == "completed"


# ---------------------------------------------------------------------------
# PUT /{token}/edit  (session-gated)
# ---------------------------------------------------------------------------


def test_edit_updates_summary_and_rating(unauthed_client, respx_mock):
    _mock_token_lookup(respx_mock)
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )

    resp = unauthed_client.put(
        f"{V2_ROOT}/{PATH_TOKEN}/edit",
        json={"summary": "Updated summary", "rating": "yes"},
        headers=_auth_header(),
    )

    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_edit_merges_question_summaries(unauthed_client, respx_mock):
    _mock_token_lookup(respx_mock)
    # When question_summaries supplied, handler first reads the existing JSONB.
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200, json=[{"question_summaries": {"1": "old", "2": "keep"}}]
        )
    )
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )

    resp = unauthed_client.put(
        f"{V2_ROOT}/{PATH_TOKEN}/edit",
        json={"question_summaries": {"1": "new"}},
        headers=_auth_header(),
    )

    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# POST /{token}/approve  (session-gated)
# ---------------------------------------------------------------------------


def test_approve_sets_approved_columns(unauthed_client, respx_mock):
    _mock_token_lookup(respx_mock)
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )

    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/approve", headers=_auth_header()
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["approved_at"]


# ---------------------------------------------------------------------------
# POST /{token}/reprocess  (session-gated)
# ---------------------------------------------------------------------------


def test_reprocess_not_significant_short_circuits(unauthed_client, respx_mock):
    _mock_token_lookup(respx_mock)
    # Existing transcript + summary nearly identical to the update -> not significant.
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200,
            json=[{"scorecard_transcript": "hello world here", "summary": ""}],
        )
    )

    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/reprocess",
        json={"updated_transcript": "hello world here!"},
        headers=_auth_header(),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["reprocessing"] is False
    assert body["processing_status"] == "completed"


def test_reprocess_404_when_round_missing(unauthed_client, respx_mock):
    _mock_token_lookup(respx_mock)
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )

    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/reprocess",
        json={"updated_transcript": "x" * 50},
        headers=_auth_header(),
    )

    assert resp.status_code == 404


def test_reprocess_significant_triggers_lambda(unauthed_client, respx_mock, monkeypatch):
    _mock_token_lookup(respx_mock)
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200, json=[{"scorecard_transcript": "", "summary": ""}]
        )
    )
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )

    class _FakeFeedbackService:
        async def trigger_feedback_processing(self, cr_id, skip_prereq_check=False):
            assert skip_prereq_check is True
            return {"status": "accepted"}

    monkeypatch.setattr(pf, "get_feedback_job_service", lambda: _FakeFeedbackService())

    big_transcript = "\n".join(["meaningful line"] * 30)
    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/reprocess",
        json={"updated_transcript": big_transcript},
        headers=_auth_header(),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["reprocessing"] is True
    assert body["processing_status"] == "processing"


def test_reprocess_lambda_failure_still_saves(unauthed_client, respx_mock, monkeypatch):
    _mock_token_lookup(respx_mock)
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200, json=[{"scorecard_transcript": "", "summary": ""}]
        )
    )
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )

    class _FakeFeedbackService:
        async def trigger_feedback_processing(self, cr_id, skip_prereq_check=False):
            raise RuntimeError("lambda boom")

    monkeypatch.setattr(pf, "get_feedback_job_service", lambda: _FakeFeedbackService())

    big_transcript = "\n".join(["meaningful line"] * 30)
    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/reprocess",
        json={"updated_transcript": big_transcript},
        headers=_auth_header(),
    )

    assert resp.status_code == 200
    body = resp.json()
    # Failure path: feedback saved but reprocessing did not start.
    assert body["success"] is True
    assert body["reprocessing"] is False
    assert body["processing_status"] == "pending"


def test_reprocess_lambda_not_accepted_returns_pending(unauthed_client, respx_mock, monkeypatch):
    _mock_token_lookup(respx_mock)
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200, json=[{"scorecard_transcript": "", "summary": ""}]
        )
    )
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )

    class _FakeFeedbackService:
        async def trigger_feedback_processing(self, cr_id, skip_prereq_check=False):
            return {"status": "skipped"}

    monkeypatch.setattr(pf, "get_feedback_job_service", lambda: _FakeFeedbackService())

    big_transcript = "\n".join(["meaningful line"] * 30)
    resp = unauthed_client.post(
        f"{V2_ROOT}/{PATH_TOKEN}/reprocess",
        json={"updated_transcript": big_transcript},
        headers=_auth_header(),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["reprocessing"] is False
    assert body["processing_status"] == "pending"


# ---------------------------------------------------------------------------
# POST /validate-session  (no path token, body only)
# ---------------------------------------------------------------------------


def test_validate_session_valid(unauthed_client, respx_mock):
    resp = unauthed_client.post(
        f"{V2_ROOT}/validate-session",
        json={"session_token": _valid_session_token()},
    )
    assert resp.status_code == 200
    assert resp.json() == {"valid": True}


def test_validate_session_invalid(unauthed_client, respx_mock):
    resp = unauthed_client.post(
        f"{V2_ROOT}/validate-session",
        json={"session_token": "garbage"},
    )
    assert resp.status_code == 401
