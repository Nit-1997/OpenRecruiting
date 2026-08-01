"""Candidate-screening invite tokens — mint + OTP/session reuse.

Two pieces:

  ScreeningInviteService.send_invite_email_for_token()
      Email a candidate the verify link for an invite token. The atomic
      candidate-upsert + candidate_round + invite insert (used by the batch
      /invite route) lives in the `screening_create_invite` RPC; this helper
      sends the email for that already-persisted token outside the transaction.

  ScreeningOTPService.verify_invite_otp()
      Reuse OTPService's verify state machine (3-attempt lockout, success-count
      cap, OTP-expiry) against the `screening_invites` table — NO copy-paste of
      the OTP algorithm — and layer the link-window (`expires_at`) check on top.
      Past the window raises InviteExpiredError (the verify route maps it to 410).

Async invariant: all DB I/O goes through the custom async Supabase client
(execute_async), never the sync .execute twin.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from app.api.v2.core.rpc import call_rpc
from app.config import get_settings
from app.services.email.service import get_email_service
from app.services.otp_service import get_otp_service
from app.utils import parse_iso_datetime

# The OTP state machine writes back to this table for screening invites.
SCREENING_INVITES_TABLE = "screening_invites"


class InviteExpiredError(Exception):
    """The invite's link-validity window (expires_at) has elapsed.

    Distinct from an expired OTP code: the whole invite is dead and a new one
    must be issued. The verify route maps this to HTTP 410 Gone.
    """


class ScreeningInviteService:
    def __init__(self):
        self._email_service = None

    @property
    def email_service(self):
        if self._email_service is None:
            self._email_service = get_email_service()
        return self._email_service

    @property
    def settings(self):
        return get_settings()

    async def send_invite_email_for_token(
        self,
        *,
        email: str,
        token: str,
        role_title: str | None = None,
        candidate_name: str | None = None,
        validity_days: int,
    ) -> None:
        """Email an invite for a token minted elsewhere (e.g. by the batch RPC).

        The route's atomic RPC creates the invite row; this sends the email for
        that already-persisted token outside the DB transaction.
        """
        await self._send_invite_email(
            email=email,
            token=token,
            role_title=role_title,
            candidate_name=candidate_name,
            validity_days=validity_days,
        )

    async def invite_existing_candidate_round(
        self,
        *,
        candidate_round_id: str,
        email: str,
        validity_days: int,
        role_title: str | None = None,
        candidate_name: str | None = None,
    ) -> dict:
        """Mint a fresh screening invite for an ALREADY-EXISTING candidate_round.

        The bulk recruiter invite (`screening_create_invite` RPC) CREATES the
        candidate + round + invite. Here the candidate_round already exists (the
        pipeline candidate has rounds), so this only mints a token + expiry,
        supersedes any prior active invite for that round, persists the new
        invite, and emails it. The atomic delete-then-insert lives in the
        `screening_invite_existing` RPC (migration 115) to satisfy the
        uq_screening_invite_active guard + the atomic-mutation invariant.

        Returns {token, expires_at, verify_url}. The email send failing does NOT
        raise — the invite row is already live; the caller still gets the
        verify_url so a copy-link affordance works even without local email.
        """
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(days=validity_days)

        await call_rpc(
            self._supabase_or_admin(),
            "screening_invite_existing",
            {
                "p": {
                    "candidate_round_id": candidate_round_id,
                    "email": email,
                    "token": token,
                    "expires_at": expires_at.isoformat(),
                }
            },
        )

        try:
            await self.send_invite_email_for_token(
                email=email,
                token=token,
                role_title=role_title,
                candidate_name=candidate_name,
                validity_days=validity_days,
            )
        except Exception:
            # Invite row is persisted; only the email send failed. The verify_url
            # below still lets the recruiter copy-share the link manually.
            pass

        verify_url = f"{self.settings.RECRUITER_PORTAL_URL}/screening/{token}/verify"
        return {
            "token": token,
            "expires_at": expires_at.isoformat(),
            "verify_url": verify_url,
        }

    def _supabase_or_admin(self):
        from app.services.supabase import get_supabase_admin_client

        return get_supabase_admin_client()

    async def _send_invite_email(
        self,
        *,
        email: str,
        token: str,
        role_title: str | None,
        candidate_name: str | None,
        validity_days: int,
    ) -> None:
        verify_link = f"{self.settings.RECRUITER_PORTAL_URL}/screening/{token}/verify"
        validity_window = (
            "1 day" if validity_days == 1 else f"{validity_days} days"
        )
        role = role_title or "the role"
        context = {
            "candidate_name": candidate_name or "there",
            "role_title": role,
            "verify_link": verify_link,
            "validity_window": validity_window,
        }
        subject = f"You're invited to a screening interview for {role}"
        await self.email_service.send_templated_email(
            to_email=email,
            to_name=candidate_name,
            subject=subject,
            template_name="screening_invite.html",
            context=context,
        )


class ScreeningOTPService:
    """Thin reuse layer: delegates the OTP verify state machine to OTPService
    against the screening_invites table, plus the link-window check."""

    def __init__(self):
        self._otp_service = None

    @property
    def otp_service(self):
        if self._otp_service is None:
            self._otp_service = get_otp_service()
        return self._otp_service

    def is_invite_expired(self, invite: dict) -> bool:
        expires_at = invite.get("expires_at")
        if not expires_at:
            # NOT NULL in the schema; treat a missing value defensively as live
            # rather than killing a valid invite on a malformed read.
            return False
        if isinstance(expires_at, str):
            expires_at = parse_iso_datetime(expires_at)
        return datetime.now(timezone.utc) > expires_at

    async def verify_invite_otp(
        self, invite: dict, submitted_otp: str
    ) -> tuple[bool, str | None]:
        """Reject if the invite's link window has elapsed, else run the SHARED
        OTPService verify state machine against the screening_invites table."""
        if self.is_invite_expired(invite):
            raise InviteExpiredError("Screening invite link has expired")
        return await self.otp_service.verify_otp(
            invite, submitted_otp, table=SCREENING_INVITES_TABLE
        )


@lru_cache()
def get_screening_invite_service() -> ScreeningInviteService:
    return ScreeningInviteService()


@lru_cache()
def get_screening_otp_service() -> ScreeningOTPService:
    return ScreeningOTPService()
