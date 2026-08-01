"""Canonical scorecard/evaluation models (the interviewer's assessment)."""

from pydantic import BaseModel, Field


class AtsScorecardAttribute(BaseModel):
    name: str
    # bool first in the union so Pydantic keeps Ashby Boolean fields as bool (not coerced
    # to int 1), letting normalize_recommendation drop them instead of reading 1→strong_no.
    rating: bool | str | int | None = None   # provider-native rating (e.g. Ashby 1-4)
    note: str | None = None
    type: str | None = None           # e.g. Skill | Qualification | Trait


class AtsScorecard(BaseModel):
    id: str | None = None
    interviewer_id: str | None = None
    interviewer_name: str | None = None
    recommendation: str | int | None = None
    submitted_at: str | None = None
    interview_id: str | None = None
    summary: str | None = None
    attributes: list[AtsScorecardAttribute] = Field(default_factory=list)
