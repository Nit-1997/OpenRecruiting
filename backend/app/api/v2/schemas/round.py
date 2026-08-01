"""Round / plan-mutation request schemas."""

from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class FeedbackQuestionInput(BaseModel):
    heading: str
    description: Optional[str] = None
    question_number: Optional[int] = None


class AddRoundRequest(BaseModel):
    name: str
    category: Optional[str] = None
    duration_minutes: int = 45
    position: Optional[int] = None
    description: Optional[str] = None
    skills: Optional[List[str]] = None
    guidelines: Optional[List[dict]] = None
    feedback_questions: Optional[List[FeedbackQuestionInput]] = None


class UpdateRoundRequest(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    duration_minutes: Optional[int] = None
    description: Optional[str] = None
    skills: Optional[List[str]] = None
    guidelines: Optional[List[dict]] = None


class ReorderRoundItem(BaseModel):
    round_id: UUID
    round_number: int


class AddQuestionRequest(BaseModel):
    heading: str
    description: Optional[str] = None
    question_number: Optional[int] = None


class UpdateQuestionRequest(BaseModel):
    heading: Optional[str] = None
    description: Optional[str] = None
    question_number: Optional[int] = None


class PlanQuestionResponse(BaseModel):
    id: Optional[UUID] = None
    question_number: Optional[int] = None
    heading: Optional[str] = None
    description: Optional[str] = None


class PlanRoundResponse(BaseModel):
    id: Optional[UUID] = None
    round_number: Optional[int] = None
    name: Optional[str] = None
    category: Optional[str] = None
    duration_minutes: Optional[int] = None
    description: Optional[str] = None
    skills: List[str] = []
    guidelines: List[dict] = []
    ai_screenable: bool = False
    ai_screenable_reason: Optional[str] = None
    feedback_questions: List[PlanQuestionResponse] = []


class RolePlanResponse(BaseModel):
    rounds: List[PlanRoundResponse] = []
