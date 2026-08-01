"""Focused tests for the extracted `require_feedback_session` dependency.

These exercise the shared session-JWT gate on a representative endpoint
(`GET /public/feedback/{token}/review`): missing token -> 401, invalid token
-> 401, token_id mismatch -> 403, valid token -> 200. The gate is identical
across /session, /start-voice, /review, /edit, /approve, /reprocess, so one
endpoint's coverage validates the shared dependency.
"""
import httpx

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


def _token_record_with_join():
    """`get_token_record` selects feedback_access_tokens with an !inner join on
    candidate_rounds (and nested candidates/rounds). Build a record shaped like
    that join result."""
    record = make_feedback_access_token()
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
    return record


def _valid_session_token(token_id=FEEDBACK_TOKEN_ID):
    otp_service = get_otp_service()
    session_token, _ = otp_service.create_session_token(
        token_id=token_id,
        interviewer_email="interviewer@test.com",
        candidate_round_id=CANDIDATE_ROUND_ID,
    )
    return session_token


def _mock_token_lookup(respx_mock):
    respx_mock.get(rest_url("feedback_access_tokens")).mock(
        return_value=httpx.Response(200, json=[_token_record_with_join()])
    )


def test_review_401_when_no_session_token(unauthed_client, respx_mock):
    _mock_token_lookup(respx_mock)

    resp = unauthed_client.get(f"{V2_ROOT}/{PATH_TOKEN}/review")

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Session token required"


def test_review_401_when_session_token_invalid(unauthed_client, respx_mock):
    _mock_token_lookup(respx_mock)

    resp = unauthed_client.get(
        f"{V2_ROOT}/{PATH_TOKEN}/review",
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid or expired session token"


def test_review_403_when_token_id_mismatch(unauthed_client, respx_mock):
    _mock_token_lookup(respx_mock)
    # Valid JWT, but minted for a different token_id than the path token resolves to.
    mismatched = _valid_session_token(token_id="00000000-0000-0000-0000-0000000000ff")

    resp = unauthed_client.get(
        f"{V2_ROOT}/{PATH_TOKEN}/review",
        headers={"Authorization": f"Bearer {mismatched}"},
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Session token does not match feedback link"


def test_review_200_with_valid_session_token_via_header(unauthed_client, respx_mock):
    _mock_token_lookup(respx_mock)
    # /review reads candidate_rounds (single) then feedback_questions.
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": CANDIDATE_ROUND_ID,
                "summary": "Strong hire",
                "rating": "strong_yes",
                "question_summaries": {},
                "processing_status": "completed",
                "scheduled_at": None,
                "round_id": ROUND_ID,
                "feedback_approved_at": None,
                "feedback_approved_by_email": None,
                "feedback_voice_session_status": None,
                "feedback_voice_session_error": None,
            }],
        )
    )
    respx_mock.get(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(200, json=[])
    )

    resp = unauthed_client.get(
        f"{V2_ROOT}/{PATH_TOKEN}/review",
        headers={"Authorization": f"Bearer {_valid_session_token()}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["candidate_round_id"] == CANDIDATE_ROUND_ID
    assert body["summary"] == "Strong hire"
    assert body["rating"] == "strong_yes"


def test_review_200_with_valid_session_token_via_query_param(unauthed_client, respx_mock):
    """The gate also accepts the JWT via the `session_token` query param, not
    just the Authorization header."""
    _mock_token_lookup(respx_mock)
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": CANDIDATE_ROUND_ID,
                "summary": "Strong hire",
                "rating": "strong_yes",
                "question_summaries": {},
                "processing_status": "completed",
                "scheduled_at": None,
                "round_id": ROUND_ID,
                "feedback_approved_at": None,
                "feedback_approved_by_email": None,
                "feedback_voice_session_status": None,
                "feedback_voice_session_error": None,
            }],
        )
    )
    respx_mock.get(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(200, json=[])
    )

    resp = unauthed_client.get(
        f"{V2_ROOT}/{PATH_TOKEN}/review",
        params={"session_token": _valid_session_token()},
    )

    assert resp.status_code == 200


def test_session_endpoint_keeps_longer_missing_token_message(unauthed_client, respx_mock):
    """`/session` historically returned a longer 401 message than the others;
    the parameterized dependency preserves that exact contract."""
    _mock_token_lookup(respx_mock)

    resp = unauthed_client.get(f"{V2_ROOT}/{PATH_TOKEN}/session")

    assert resp.status_code == 401
    assert resp.json()["detail"] == (
        "Session token required. Provide via Authorization header or "
        "session_token query parameter."
    )
