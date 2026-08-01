"""Candidate / per-candidate-round mutation request schemas."""

from typing import List, Optional

from pydantic import BaseModel, EmailStr

from app.api.v2.schemas.round import FeedbackQuestionInput


class CreateCandidateRequest(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    resume_url: Optional[str] = None
    # Accepted for forward-compat (spec §15) but dropped before the DB —
    # there is no `source` column on `candidates` today.
    source: Optional[str] = None


class AddCustomRoundRequest(BaseModel):
    name: str
    category: Optional[str] = None
    duration_minutes: int = 45
    description: Optional[str] = None
    skills: Optional[List[str]] = None
    guidelines: Optional[List[dict]] = None
    feedback_questions: Optional[List[FeedbackQuestionInput]] = None
