"""Interviewer-feedback request schemas."""

from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.api.v2.schemas.common import EvidenceStatus, RoundRating


class FeedbackEntry(BaseModel):
    feedback_question_id: UUID
    feedback_text: str
    evidence_status: EvidenceStatus
    evidence: Optional[List[str]] = None


class SubmitFeedbackRequest(BaseModel):
    entries: List[FeedbackEntry]
    rating: RoundRating
    summary: str
    # Spec §8.2 mentions an optional `scorecard` field for forward-compat,
    # but there is no DB column for it today — accepted and dropped.
    scorecard: Optional[dict] = None


class RequestFeedbackRequest(BaseModel):
    interviewer_email: EmailStr
    interviewer_name: Optional[str] = None
    channel: Literal["email"] = "email"


class ReprocessRequest(BaseModel):
    force: bool = False
