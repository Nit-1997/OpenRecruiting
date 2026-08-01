"""Schemas for POST /intake/parse-intent — free-text role intent → form fields."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ParseIntentRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


class ParseIntentResponse(BaseModel):
    role_name: str | None = None
    exp_min: int | None = None
    exp_max: int | None = None
    location: str | None = None
    intent: str = "other"
    list_status: str | None = None
