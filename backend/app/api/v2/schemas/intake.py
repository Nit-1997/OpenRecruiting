"""Pydantic request/response DTOs for v2 intake API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class IntakeFormData(BaseModel):
    role_name: str = Field(..., min_length=1, max_length=200)
    experience_min: int = Field(..., ge=0, le=50)
    # Optional: None means open-ended ("X+ years"). The requisitions table
    # column is nullable and CHECK (max IS NULL OR max >= min) — mirroring how
    # v1 modelled it. NEVER coerce a blank max to 0; that violates the CHECK
    # whenever min > 0 (the 23514 the create-role flow used to surface).
    experience_max: Optional[int] = Field(None, ge=0, le=50)
    location: str = Field(..., min_length=1, max_length=200)
    jd_text: Optional[str] = Field(None, max_length=50_000)


class CreateSessionRequest(BaseModel):
    # Either a fresh-role form OR an existing requisition to complete intake
    # for (ATS-imported / awaiting publish). With requisition_id the service
    # seeds form_data from the requisition row and form_data is ignored.
    form_data: Optional[IntakeFormData] = None
    requisition_id: Optional[UUID] = None
    entry_point: Optional[str] = Field(
        None,
        description=(
            "One of: create_role_btn | intake_tab | supervisor_handoff | "
            "complete_intake_btn"
        ),
    )

    @model_validator(mode="after")
    def _require_form_or_requisition(self) -> "CreateSessionRequest":
        if self.form_data is None and self.requisition_id is None:
            raise ValueError(
                "form_data is required when requisition_id is not provided"
            )
        return self


class CreateSessionResponse(BaseModel):
    session_id: UUID
    requisition_id: UUID


class ProcessStage(BaseModel):
    name: str
    status: str  # pending | running | completed | failed
    output: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    updated_at: Optional[datetime] = None


class VoiceStartRequest(BaseModel):
    sdp: str = Field(..., description="WebRTC offer SDP")
    type: str = Field("offer", description="WebRTC offer type")


class VoiceStartResponse(BaseModel):
    sdp: str = Field(..., description="WebRTC answer SDP")
    type: str = Field("answer", description="WebRTC answer type")


class IntakeSessionResponse(BaseModel):
    id: UUID
    requisition_id: UUID
    user_id: UUID
    organization_id: UUID
    status: str
    active_modality: Optional[str] = None
    entry_point: Optional[str] = None
    form_data: dict[str, Any]
    questions_version: str
    questions_snapshot: list[dict[str, Any]]
    prefilled_answers: Optional[dict[str, Any]] = None
    current_answers: Optional[dict[str, Any]] = None
    turns: list[dict[str, Any]] = Field(default_factory=list)
    process_stages: list[ProcessStage] = Field(default_factory=list)
    process_status: str = "idle"
    process_error: Optional[str] = None
    interview_plan: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


class PublishRequest(BaseModel):
    """Optional edited plan override. If null, server uses DB-stored interview_plan."""
    interview_plan: Optional[dict[str, Any]] = None


class SubmitResponse(BaseModel):
    session_id: UUID
    status: str


class PublishResponse(BaseModel):
    session_id: UUID
    requisition_id: UUID
    redirect_url: str


# ---------------------------------------------------------------------------
# GET /api/v2/intake/sessions — list view (B1.1)
# ---------------------------------------------------------------------------


class SessionListItem(BaseModel):
    """Single row in the conversation-history list, from user_conversation_history view."""

    session_id: UUID
    requisition_id: UUID
    title: str
    display_status: Literal["incomplete", "submitted", "completed"]
    detail_status: str
    last_activity_at: datetime
    active_modality: Optional[Literal["voice", "text"]] = None
    resume_url: str
    role_name: Optional[str] = None
    exp_min: Optional[int] = None
    exp_max: Optional[int] = None
    location: Optional[str] = None

    # Hub enrichment — goal coverage for the "Continue pending" list
    covered: int = 0
    total: int = 9
    stopped_at: Optional[str] = None

    # Hub enrichment — plan stats for the "Edit existing" list
    rounds_count: int = 0
    total_minutes: int = 0
    candidates_count: int = 0


class ListSessionsResponse(BaseModel):
    sessions: list[SessionListItem]


# ---------------------------------------------------------------------------
# B2.1 — PATCH /api/v2/intake/sessions/{id}/answers
# ---------------------------------------------------------------------------

QuestionIdLiteral = Literal[
    "q1_role_overview", "q2_rounds", "q3_focus_areas", "q4_must_haves",
    "q5_nice_to_haves", "q6_cultural_fit", "q7_team_structure",
    "q8_red_flags", "q9_anything_else",
]

AnswerStatusLiteral = Literal[
    "untouched", "needs_probe", "discussed", "validated", "skipped",
]


class PatchAnswerEntry(BaseModel):
    """Per-question patch — at least one of text|status must be provided."""
    text: Optional[str] = Field(None, max_length=20_000)
    status: Optional[AnswerStatusLiteral] = None

    def model_post_init(self, __context) -> None:
        if self.text is None and self.status is None:
            raise ValueError("patch entry must include text or status")


class PatchAnswersRequest(BaseModel):
    patch: dict[QuestionIdLiteral, PatchAnswerEntry]

    @model_validator(mode="after")
    def _patch_not_empty(self) -> "PatchAnswersRequest":
        if not self.patch:
            raise ValueError("patch must not be empty (min 1 entry required)")
        return self


class PatchAnswersResponse(BaseModel):
    applied: list[QuestionIdLiteral]
