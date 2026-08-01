"""Behavioural tests for the candidate-screening invite flow.

Covers:
  - ScreeningOTPService: the OTP verify state machine is REUSED from OTPService
    (not re-implemented) against the screening_invites table, plus the extra
    expires_at link-window check (410-equivalent) layered on top.

The DB boundary is a fluent MagicMock; clock-dependent branches use real
datetime offsets so they stay deterministic. The email boundary is a stub
injected onto the service's lazy backing field.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.screening_invite_service import (
    ScreeningInviteService,
    ScreeningOTPService,
    InviteExpiredError,
)


@pytest.fixture
def now():
    return datetime.now(timezone.utc)


# --- fakes -----------------------------------------------------------------
class _EmailResult:
    success = True
    message_id = "msg-1"


class _FakeEmail:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_templated_email(self, to_email, to_name, subject, template_name, context):
        self.sent.append({
            "to_email": to_email,
            "subject": subject,
            "template": template_name,
            "context": context,
        })
        return _EmailResult()


def _fluent_supabase():
    builder = MagicMock()
    for m in ("table", "select", "insert", "update", "delete", "eq", "is_", "is_null", "limit", "order", "single"):
        getattr(builder, m).return_value = builder
    builder.execute_async = AsyncMock(return_value=MagicMock(data=[]))
    supa = MagicMock()
    supa.table.return_value = builder
    return supa, builder


def _make_invite_service():
    svc = ScreeningInviteService()
    svc._email_service = _FakeEmail()
    return svc


# ---------------------------------------------------------------------------
# send_invite_email_for_token — email send for an externally-minted token
# ---------------------------------------------------------------------------


async def test_send_invite_email_for_token():
    svc = _make_invite_service()

    await svc.send_invite_email_for_token(
        email="cand@example.com",
        token="tok-abc",
        role_title="Backend Engineer",
        candidate_name="Cand",
        validity_days=7,
    )

    assert len(svc._email_service.sent) == 1
    sent = svc._email_service.sent[0]
    assert sent["to_email"] == "cand@example.com"
    assert sent["template"] == "screening_invite.html"
    # Verify link is the screening verify path with the provided token.
    assert "/screening/tok-abc/verify" in sent["context"]["verify_link"]


# ---------------------------------------------------------------------------
# invite_existing_candidate_round — per-candidate-round invite (round exists)
# ---------------------------------------------------------------------------


async def test_invite_existing_mints_token_expiry_and_verify_url():
    """Mints a fresh token + X-day expiry, calls the supersede RPC, emails the
    invite, and returns {token, expires_at, verify_url} for the copy-link."""
    svc = _make_invite_service()
    rpc_calls: list = []

    async def _fake_call_rpc(supabase, name, params):
        rpc_calls.append((name, params))
        return {"token": params["p"]["token"]}

    with patch(
        "app.services.screening_invite_service.call_rpc", _fake_call_rpc
    ), patch(
        "app.services.supabase.get_supabase_admin_client",
        return_value=MagicMock(),
    ):
        result = await svc.invite_existing_candidate_round(
            candidate_round_id="cr-123",
            email="Pipeline@Example.com",
            validity_days=10,
            role_title="Staff Engineer",
            candidate_name="Pat",
        )

    # Token present, distinct, and reflected into the verify_url.
    assert result["token"]
    assert f"/screening/{result['token']}/verify" in result["verify_url"]
    # Expiry is ~validity_days out.
    expires = datetime.fromisoformat(result["expires_at"])
    delta = expires - datetime.now(timezone.utc)
    assert timedelta(days=9, hours=23) < delta <= timedelta(days=10)

    # The supersede RPC was invoked for the existing candidate_round.
    assert len(rpc_calls) == 1
    name, params = rpc_calls[0]
    assert name == "screening_invite_existing"
    assert params["p"]["candidate_round_id"] == "cr-123"
    # Email normalised lowercase into the RPC payload.
    assert params["p"]["email"] == "Pipeline@Example.com"  # service passes raw; route lowers
    assert params["p"]["token"] == result["token"]

    # The invite email was sent for the same token.
    assert len(svc._email_service.sent) == 1
    sent = svc._email_service.sent[0]
    assert f"/screening/{result['token']}/verify" in sent["context"]["verify_link"]


async def test_invite_existing_returns_link_even_when_email_fails():
    """Email send failures must NOT raise — the invite row is live and the
    recruiter still needs the verify_url to copy-share it."""
    svc = ScreeningInviteService()

    class _BoomEmail:
        async def send_templated_email(self, **kwargs):
            raise RuntimeError("smtp down")

    svc._email_service = _BoomEmail()

    async def _fake_call_rpc(supabase, name, params):
        return {"token": params["p"]["token"]}

    with patch(
        "app.services.screening_invite_service.call_rpc", _fake_call_rpc
    ), patch(
        "app.services.supabase.get_supabase_admin_client",
        return_value=MagicMock(),
    ):
        result = await svc.invite_existing_candidate_round(
            candidate_round_id="cr-999",
            email="x@y.com",
            validity_days=7,
        )

    assert result["token"]
    assert result["verify_url"].endswith(f"/screening/{result['token']}/verify")


# ---------------------------------------------------------------------------
# ScreeningOTPService — link-window (expires_at) gate
# ---------------------------------------------------------------------------


def _future_iso(minutes=30):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _past_iso(minutes=30):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


async def test_expired_invite_rejected():
    """When now() > expires_at, the screening OTP path rejects before any OTP work."""
    svc = ScreeningOTPService()
    invite = {
        "id": "inv-1",
        "otp_code": "111111",
        "otp_expires_at": _future_iso(),
        "expires_at": _past_iso(),  # link window elapsed
    }
    with pytest.raises(InviteExpiredError):
        await svc.verify_invite_otp(invite, "111111")


async def test_active_invite_verifies_via_reused_otp():
    """A live invite delegates to the shared OTPService.verify_otp (success path)."""
    supa, builder = _fluent_supabase()
    svc = ScreeningOTPService()
    invite = {
        "id": "inv-2",
        "otp_code": "111111",
        "otp_expires_at": _future_iso(),
        "expires_at": _future_iso(60 * 24),  # link still valid
        "otp_success_count": 0,
    }
    with patch("app.services.otp_service.get_supabase_admin_client", return_value=supa):
        ok, err = await svc.verify_invite_otp(invite, "111111")
    assert ok is True and err is None
    # The reused OTP machine wrote back to the screening_invites table, NOT
    # feedback_access_tokens — proving the table parameterization.
    supa.table.assert_any_call("screening_invites")
    builder.update.assert_called()


# ---------------------------------------------------------------------------
# OTP reuse: the 3-attempt lockout is enforced via the SHARED machine
# ---------------------------------------------------------------------------


async def test_screening_path_enforces_attempt_lock():
    """At MAX_ATTEMPTS-1 prior failures, one more wrong code locks the invite —
    the lockout is the reused OTPService logic, not a re-implementation."""
    supa, _ = _fluent_supabase()
    svc = ScreeningOTPService()
    invite = {
        "id": "inv-3",
        "otp_code": "111111",
        "otp_expires_at": _future_iso(),
        "expires_at": _future_iso(60 * 24),
        "otp_attempts": svc.otp_service.MAX_ATTEMPTS - 1,
    }
    with patch("app.services.otp_service.get_supabase_admin_client", return_value=supa):
        ok, err = await svc.verify_invite_otp(invite, "999999")
    assert ok is False and "locked" in err.lower()
    # And the write targeted the screening table.
    supa.table.assert_any_call("screening_invites")


async def test_screening_path_wrong_code_decrements_attempts():
    supa, _ = _fluent_supabase()
    svc = ScreeningOTPService()
    invite = {
        "id": "inv-4",
        "otp_code": "111111",
        "otp_expires_at": _future_iso(),
        "expires_at": _future_iso(60 * 24),
        "otp_attempts": 0,
    }
    with patch("app.services.otp_service.get_supabase_admin_client", return_value=supa):
        ok, err = await svc.verify_invite_otp(invite, "999999")
    assert ok is False and "remaining" in err
