import hmac
import secrets
from datetime import datetime, timezone, timedelta
import jwt
from functools import lru_cache

from app.services.supabase import get_supabase_admin_client
from app.config import get_settings
from app.logging_config import get_logger
from app.utils import parse_iso_datetime

logger = get_logger(__name__)


class OTPService:
    OTP_VALIDITY_MINUTES = 720
    MAX_ATTEMPTS = 3
    MAX_SUCCESSFUL_VERIFICATIONS = 3
    LOCKOUT_MINUTES = 2
    RATE_LIMIT_SECONDS = 60
    SESSION_HOURS = 24

    def __init__(self):
        self._settings = None

    @property
    def settings(self):
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def generate_otp(self, length: int = 6) -> str:
        return "".join(secrets.choice("0123456789") for _ in range(length))

    def generate_feedback_token(self, length: int = 32) -> str:
        return secrets.token_urlsafe(length)

    async def is_interviewer_registered(self, email: str) -> bool:
        supabase = get_supabase_admin_client()
        try:
            result = await supabase.table("profiles").select("id, invitation_status").eq(
                "email", email.lower()
            ).execute_async()

            if result.data and len(result.data) > 0:
                profile = result.data[0]
                if profile.get("invitation_status") == "signed_up":
                    logger.info(f"Interviewer {email} is a registered OpenRecruiting user")
                    return True
            return False
        except Exception as e:
            logger.error(f"Error checking if interviewer is registered: {e}")
            return False

    def can_send_otp(self, token_record: dict) -> tuple[bool, str | None]:
        otp_last_sent_at = token_record.get("otp_last_sent_at")
        if not otp_last_sent_at:
            return (True, None)

        if isinstance(otp_last_sent_at, str):
            last_sent = parse_iso_datetime(otp_last_sent_at)
        else:
            last_sent = otp_last_sent_at

        now = datetime.now(timezone.utc)
        elapsed = (now - last_sent).total_seconds()

        if elapsed < self.RATE_LIMIT_SECONDS:
            wait_seconds = int(self.RATE_LIMIT_SECONDS - elapsed)
            return (False, f"Please wait {wait_seconds} seconds before requesting a new code")

        return (True, None)

    def is_locked(self, token_record: dict) -> tuple[bool, datetime | None]:
        otp_locked_until = token_record.get("otp_locked_until")
        if not otp_locked_until:
            return (False, None)

        if isinstance(otp_locked_until, str):
            locked_until = parse_iso_datetime(otp_locked_until)
        else:
            locked_until = otp_locked_until

        now = datetime.now(timezone.utc)
        if now < locked_until:
            return (True, locked_until)

        return (False, None)

    async def verify_otp(
        self,
        token_record: dict,
        submitted_otp: str,
        table: str = "feedback_access_tokens",
    ) -> tuple[bool, str | None]:
        """Verify an OTP against ``token_record`` and persist the resulting
        attempt/lockout/success state.

        ``table`` selects which table the state writes land in. It defaults to
        ``feedback_access_tokens`` so every existing feedback call site behaves
        identically; the candidate-screening flow passes ``screening_invites``
        to reuse this exact state machine against its own table.
        """
        token_id = token_record.get("id")
        supabase = get_supabase_admin_client()

        locked, locked_until = self.is_locked(token_record)
        if locked:
            minutes_remaining = int((locked_until - datetime.now(timezone.utc)).total_seconds() / 60) + 1
            return (False, f"Account locked. Try again in {minutes_remaining} minutes.")

        stored_otp = token_record.get("otp_code")
        otp_expires_at = token_record.get("otp_expires_at")

        if not stored_otp or not otp_expires_at:
            return (False, "No active verification code. Please request a new one.")

        if isinstance(otp_expires_at, str):
            expires_at = parse_iso_datetime(otp_expires_at)
        else:
            expires_at = otp_expires_at

        now = datetime.now(timezone.utc)
        if now > expires_at:
            await supabase.table(table).update({
                "otp_code": None,
                "otp_expires_at": None,
                "updated_at": now.isoformat(),
            }).eq("id", token_id).execute_async()
            return (False, "Verification code has expired. Please request a new one.")

        submitted = submitted_otp.strip()
        if not hmac.compare_digest(submitted, stored_otp):
            current_attempts = token_record.get("otp_attempts", 0) + 1

            update_data = {
                "otp_attempts": current_attempts,
                "updated_at": now.isoformat(),
            }

            if current_attempts >= self.MAX_ATTEMPTS:
                lockout_until = now + timedelta(minutes=self.LOCKOUT_MINUTES)
                update_data["otp_locked_until"] = lockout_until.isoformat()
                update_data["otp_code"] = None
                update_data["otp_expires_at"] = None
                logger.warning(f"OTP verification locked for token {token_id} after {current_attempts} attempts")

            await supabase.table(table).update(update_data).eq("id", token_id).execute_async()

            attempts_remaining = self.MAX_ATTEMPTS - current_attempts
            if attempts_remaining > 0:
                return (False, f"Invalid code. {attempts_remaining} attempts remaining.")
            else:
                return (False, f"Too many failed attempts. Account locked for {self.LOCKOUT_MINUTES} minutes.")

        success_count = token_record.get("otp_success_count", 0)
        if success_count >= self.MAX_SUCCESSFUL_VERIFICATIONS:
            return (False, "Code has been used the maximum number of times. Please request a new one.")

        new_count = success_count + 1
        update_data = {
            "otp_success_count": new_count,
            "otp_attempts": 0,
            "otp_locked_until": None,
            "updated_at": now.isoformat(),
            "last_accessed_at": now.isoformat(),
        }

        if new_count >= self.MAX_SUCCESSFUL_VERIFICATIONS:
            update_data["otp_code"] = None
            update_data["otp_expires_at"] = None

        await supabase.table(table).update(update_data).eq("id", token_id).execute_async()

        logger.info(f"OTP verified successfully for token {token_id} (use {new_count}/{self.MAX_SUCCESSFUL_VERIFICATIONS})")
        return (True, None)

    def create_session_token(
        self, token_id: str, interviewer_email: str, candidate_round_id: str
    ) -> tuple[str, datetime]:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=self.SESSION_HOURS)

        payload = {
            "token_id": token_id,
            "email": interviewer_email,
            "candidate_round_id": candidate_round_id,
            "type": "feedback_session",
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        }

        session_token = jwt.encode(
            payload,
            self.settings.SUPABASE_JWT_SECRET,
            algorithm="HS256"
        )

        logger.info(f"Created session token for feedback access {token_id}")
        return (session_token, expires_at)

    def verify_session_token(self, session_token: str) -> dict | None:
        try:
            payload = jwt.decode(
                session_token,
                self.settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256"]
            )

            if payload.get("type") != "feedback_session":
                logger.warning("Invalid session token type")
                return None

            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Session token expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid session token: {e}")
            return None


@lru_cache()
def get_otp_service() -> OTPService:
    return OTPService()
