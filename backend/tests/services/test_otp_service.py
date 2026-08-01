"""Behavioral tests for OTPService — the OTP mint/verify/lockout state machine
and the session-JWT helpers.

DB writes go through a fluent MagicMock supabase stub; clock-dependent branches
use real `datetime.now` with relative offsets so they stay deterministic.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest

from app.services.otp_service import OTPService, get_otp_service


@pytest.fixture
def svc():
    return OTPService()


def _fluent_supabase():
    builder = MagicMock()
    for m in ("table", "select", "update", "eq", "is_", "limit", "order"):
        getattr(builder, m).return_value = builder
    builder.execute_async = AsyncMock(return_value=MagicMock(data=[]))
    supa = MagicMock()
    supa.table.return_value = builder
    return supa, builder


# ---------------------------------------------------------------------------
# generators
# ---------------------------------------------------------------------------


def test_generate_otp_is_six_digits(svc):
    code = svc.generate_otp()
    assert len(code) == 6 and code.isdigit()


def test_generate_feedback_token_is_urlsafe(svc):
    tok = svc.generate_feedback_token()
    assert isinstance(tok, str) and len(tok) > 20


# ---------------------------------------------------------------------------
# is_interviewer_registered
# ---------------------------------------------------------------------------


async def test_is_interviewer_registered_true_for_signed_up(svc):
    supa, builder = _fluent_supabase()
    builder.execute_async = AsyncMock(
        return_value=MagicMock(data=[{"id": "p1", "invitation_status": "signed_up"}])
    )
    with patch("app.services.otp_service.get_supabase_admin_client", return_value=supa):
        assert await svc.is_interviewer_registered("a@b.com") is True


async def test_is_interviewer_registered_false_when_not_signed_up(svc):
    supa, builder = _fluent_supabase()
    builder.execute_async = AsyncMock(
        return_value=MagicMock(data=[{"id": "p1", "invitation_status": "pending"}])
    )
    with patch("app.services.otp_service.get_supabase_admin_client", return_value=supa):
        assert await svc.is_interviewer_registered("a@b.com") is False


async def test_is_interviewer_registered_false_on_exception(svc):
    supa, builder = _fluent_supabase()
    builder.execute_async = AsyncMock(side_effect=RuntimeError("db down"))
    with patch("app.services.otp_service.get_supabase_admin_client", return_value=supa):
        assert await svc.is_interviewer_registered("a@b.com") is False


# ---------------------------------------------------------------------------
# can_send_otp
# ---------------------------------------------------------------------------


def test_can_send_otp_first_time(svc):
    ok, msg = svc.can_send_otp({})
    assert ok is True and msg is None


def test_can_send_otp_rate_limited(svc):
    now = datetime.now(timezone.utc).isoformat()
    ok, msg = svc.can_send_otp({"otp_last_sent_at": now})
    assert ok is False and "wait" in msg


def test_can_send_otp_after_window(svc):
    old = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    ok, msg = svc.can_send_otp({"otp_last_sent_at": old})
    assert ok is True


# ---------------------------------------------------------------------------
# is_locked
# ---------------------------------------------------------------------------


def test_is_locked_false_when_unset(svc):
    locked, until = svc.is_locked({})
    assert locked is False and until is None


def test_is_locked_true_when_future(svc):
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    locked, until = svc.is_locked({"otp_locked_until": future})
    assert locked is True and until is not None


def test_is_locked_false_when_past(svc):
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    locked, until = svc.is_locked({"otp_locked_until": past})
    assert locked is False


# ---------------------------------------------------------------------------
# verify_otp
# ---------------------------------------------------------------------------


def _future_iso(minutes=30):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _past_iso(minutes=30):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


async def test_verify_otp_locked_short_circuits(svc):
    supa, _ = _fluent_supabase()
    rec = {"id": "t1", "otp_locked_until": _future_iso(2)}
    with patch("app.services.otp_service.get_supabase_admin_client", return_value=supa):
        ok, err = await svc.verify_otp(rec, "123456")
    assert ok is False and "locked" in err.lower()


async def test_verify_otp_no_active_code(svc):
    supa, _ = _fluent_supabase()
    with patch("app.services.otp_service.get_supabase_admin_client", return_value=supa):
        ok, err = await svc.verify_otp({"id": "t1"}, "123456")
    assert ok is False and "No active" in err


async def test_verify_otp_expired_clears_code(svc):
    supa, builder = _fluent_supabase()
    rec = {"id": "t1", "otp_code": "111111", "otp_expires_at": _past_iso()}
    with patch("app.services.otp_service.get_supabase_admin_client", return_value=supa):
        ok, err = await svc.verify_otp(rec, "111111")
    assert ok is False and "expired" in err.lower()
    builder.update.assert_called()


async def test_verify_otp_wrong_code_decrements_attempts(svc):
    supa, _ = _fluent_supabase()
    rec = {"id": "t1", "otp_code": "111111", "otp_expires_at": _future_iso(), "otp_attempts": 0}
    with patch("app.services.otp_service.get_supabase_admin_client", return_value=supa):
        ok, err = await svc.verify_otp(rec, "999999")
    assert ok is False and "remaining" in err


async def test_verify_otp_wrong_code_locks_at_max(svc):
    supa, _ = _fluent_supabase()
    # Already at MAX_ATTEMPTS - 1 attempts -> this failure triggers lockout.
    rec = {
        "id": "t1",
        "otp_code": "111111",
        "otp_expires_at": _future_iso(),
        "otp_attempts": svc.MAX_ATTEMPTS - 1,
    }
    with patch("app.services.otp_service.get_supabase_admin_client", return_value=supa):
        ok, err = await svc.verify_otp(rec, "999999")
    assert ok is False and "locked" in err.lower()


async def test_verify_otp_max_successful_blocks(svc):
    supa, _ = _fluent_supabase()
    rec = {
        "id": "t1",
        "otp_code": "111111",
        "otp_expires_at": _future_iso(),
        "otp_success_count": svc.MAX_SUCCESSFUL_VERIFICATIONS,
    }
    with patch("app.services.otp_service.get_supabase_admin_client", return_value=supa):
        ok, err = await svc.verify_otp(rec, "111111")
    assert ok is False and "maximum" in err.lower()


async def test_verify_otp_success(svc):
    supa, builder = _fluent_supabase()
    rec = {
        "id": "t1",
        "otp_code": "111111",
        "otp_expires_at": _future_iso(),
        "otp_success_count": 0,
    }
    with patch("app.services.otp_service.get_supabase_admin_client", return_value=supa):
        ok, err = await svc.verify_otp(rec, "111111")
    assert ok is True and err is None
    builder.update.assert_called()


async def test_verify_otp_default_table_is_feedback_access_tokens(svc):
    """Default (no table arg) writes back to feedback_access_tokens — the
    existing feedback behaviour must be byte-for-byte unchanged."""
    supa, _ = _fluent_supabase()
    rec = {"id": "t1", "otp_code": "111111", "otp_expires_at": _future_iso(), "otp_success_count": 0}
    with patch("app.services.otp_service.get_supabase_admin_client", return_value=supa):
        await svc.verify_otp(rec, "111111")
    supa.table.assert_any_call("feedback_access_tokens")


async def test_verify_otp_honors_table_param(svc):
    """Passing table= routes the verify state-machine's writes to that table,
    enabling reuse by the screening invite flow without copy-pasting the OTP
    algorithm."""
    supa, _ = _fluent_supabase()
    rec = {"id": "inv1", "otp_code": "111111", "otp_expires_at": _future_iso(), "otp_success_count": 0}
    with patch("app.services.otp_service.get_supabase_admin_client", return_value=supa):
        ok, err = await svc.verify_otp(rec, "111111", table="screening_invites")
    assert ok is True and err is None
    supa.table.assert_any_call("screening_invites")


# ---------------------------------------------------------------------------
# session token round-trip
# ---------------------------------------------------------------------------


def test_session_token_round_trip(svc):
    token, expires = svc.create_session_token("tid", "a@b.com", "cr1")
    payload = svc.verify_session_token(token)
    assert payload["token_id"] == "tid"
    assert payload["candidate_round_id"] == "cr1"
    assert payload["type"] == "feedback_session"
    assert expires > datetime.now(timezone.utc)


def test_verify_session_token_rejects_wrong_type(svc):
    # A JWT with the right secret but the wrong `type` is rejected.
    bad = jwt.encode(
        {"type": "other", "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())},
        svc.settings.SUPABASE_JWT_SECRET,
        algorithm="HS256",
    )
    assert svc.verify_session_token(bad) is None


def test_verify_session_token_rejects_expired(svc):
    expired = jwt.encode(
        {"type": "feedback_session", "exp": int(_past_iso_ts())},
        svc.settings.SUPABASE_JWT_SECRET,
        algorithm="HS256",
    )
    assert svc.verify_session_token(expired) is None


def test_verify_session_token_rejects_garbage(svc):
    assert svc.verify_session_token("not-a-jwt") is None


def _past_iso_ts():
    return (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()


def test_get_otp_service_is_cached():
    assert get_otp_service() is get_otp_service()
