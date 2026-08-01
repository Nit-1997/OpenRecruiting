"""Pydantic schema for replay-script input fixtures.

A Fixture captures the exact data the feedback pipeline reads from Supabase,
serialized to disk so replay runs are reproducible and don't require DB access.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RedactionInfo(BaseModel):
    candidate_name: str
    interviewer_names: dict[str, str] = Field(default_factory=dict)


class FeedbackSource(BaseModel):
    source: Literal["scorecard", "bot", "none"]
    scorecard_transcript: str | None = None
    has_interview_transcript: bool = False


class Question(BaseModel):
    id: str
    question_number: int
    heading: str
    description: str


class RoleContext(BaseModel):
    role: str
    seniority: str
    location: str
    must_have_skills: list[str] = Field(default_factory=list)
    good_to_have_skills: list[str] = Field(default_factory=list)
    intake_notes: str = ""
    job_description: str = ""


class Transcript(BaseModel):
    feedback_transcript: str = ""
    segments: list[dict] = Field(default_factory=list)
    feedback_start_timestamp: float | None = None


class BaselineOutputs(BaseModel):
    """Snapshot of the v1 (pre-change) production outputs, for diffing."""
    rating: str | None = None
    summary: str | None = None
    question_summaries: dict = Field(default_factory=dict)
    competency_snapshots: str | None = None


class Fixture(BaseModel):
    fixture_version: int = 1
    round_id: str
    captured_at: str
    source_environment: str
    redaction: RedactionInfo
    feedback_source: FeedbackSource
    questions: list[Question]
    role_context: RoleContext
    transcript: Transcript
    baseline_outputs: BaselineOutputs
