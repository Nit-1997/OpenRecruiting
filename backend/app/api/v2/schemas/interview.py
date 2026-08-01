"""Schedule / reschedule / cancel candidate-round request schemas."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, EmailStr, HttpUrl, field_validator


# How far in the past `scheduled_at` is allowed to be. Matches the 60-second
# grace in `schedule_candidate_round` / `reschedule_candidate_round` RPCs
# (migration 87) so the BE schema and the SQL guard agree.
_SCHEDULE_PAST_GRACE_SECONDS = 60


def _require_tz_aware(value: datetime) -> datetime:
    """Reject naive datetimes. Mirrors v1 behavior — the FE is expected to
    convert the recruiter's local pick to UTC with offset using the chosen
    IANA timezone, then send an offset-bearing ISO string. Without the
    offset we cannot reliably reconstruct what the recruiter meant.
    """
    if value.tzinfo is None:
        raise ValueError(
            "scheduled_at must include timezone offset "
            "(e.g. 2026-04-01T10:00:00+05:30)"
        )
    return value


def _reject_scheduled_in_past(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return value
    value = _require_tz_aware(value)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=_SCHEDULE_PAST_GRACE_SECONDS)
    if value < cutoff:
        raise ValueError(
            "scheduled_at must not be in the past "
            f"(60-second grace applies; received {value.isoformat()})"
        )
    return value


class ScheduleInterviewRequest(BaseModel):
    """POST schedule body.

    Field rules — mirrors the v1 contract so recruiters get the same UX:
      * `interviewer_email` is optional. Recruiters often don't have it at
        schedule-time; we'd rather store the round than block on missing
        contact info. When provided we still validate the format.
      * `interviewer_name` is optional. Persisted to
        `candidate_rounds.interviewer_name` (migration 89) so external
        interviewers display correctly in the drawer.
      * `meeting_url` is enforced by the FE for interview-type rounds (the
        bot needs it). We keep it optional at the schema layer because
        assessment-type rounds don't carry a URL — the FE encodes which
        is which.
      * `scheduling_timezone` is the IANA TZ name the recruiter picked
        (e.g. `America/New_York`). Persisted on candidate_rounds so the
        drawer's reschedule view can render the saved value back in the
        recruiter's chosen zone.

    `duration_minutes` was removed: the field was never persisted (no column
    on candidate_rounds, never passed to Recall bot scheduling). The round
    itself owns the canonical duration via `rounds.duration_minutes`.
    """

    scheduled_at: datetime
    interviewer_email: Optional[EmailStr] = None
    interviewer_name: Optional[str] = None
    meeting_url: Optional[HttpUrl] = None
    scheduling_timezone: Optional[str] = None

    @field_validator("scheduled_at")
    @classmethod
    def _scheduled_at_validator(cls, value: datetime) -> datetime:
        return _reject_scheduled_in_past(value)


class RescheduleInterviewRequest(BaseModel):
    """PUT reschedule body. All fields optional. To explicitly remove a
    previously-set meeting_url, send `clear_meeting_url=true`."""

    scheduled_at: Optional[datetime] = None
    interviewer_email: Optional[EmailStr] = None
    interviewer_name: Optional[str] = None
    meeting_url: Optional[HttpUrl] = None
    scheduling_timezone: Optional[str] = None
    clear_meeting_url: bool = False

    @field_validator("scheduled_at")
    @classmethod
    def _scheduled_at_validator(cls, value: Optional[datetime]) -> Optional[datetime]:
        return _reject_scheduled_in_past(value)
