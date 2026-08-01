"""Schemas for POST /assistant/route — free-text message → product-flow intent."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AssistantRouteRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


class AssistantRouteResponse(BaseModel):
    intent: Literal["browse_roles", "intake_call", "debrief", "out_of_scope"]
