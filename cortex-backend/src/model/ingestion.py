from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    candidate_round_id: str | None = None
    requisition_id: str | None = None
    candidate_id: str | None = None
    session_id: str | None = None  # v2 intake sessions


class IngestRequest(BaseModel):
    event_type: str = Field(
        ...,
        pattern=r"^(feedback_completed|plan_created|decision_made|question_summaries_available|intake_transcript_available|feedback_debrief_available|interview_transcript_available|jd_available|intake_v2_completed|recruiter_insight|candidate_profile_enriched|candidate_evaluation)$",
    )
    org_id: str
    source_ref: SourceRef
    timestamp: datetime


class IngestDirectRequest(IngestRequest):
    payload: dict[str, Any]


class IngestResponse(BaseModel):
    status: str = Field(..., pattern=r"^(ingested|partial|rejected)$")
    event_type: str
    nodes_created: int = 0
    edges_created: int = 0
    processing_time_ms: int = 0
    errors: list[str] = Field(default_factory=list)


class OrgIngestRequest(BaseModel):
    org_id: str


class OrgIngestResponse(BaseModel):
    org_id: str
    total_nodes: int = 0
    total_edges: int = 0
    total_errors: int = 0
    processing_time_ms: int = 0
    events: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class OrgForcePublishRequest(BaseModel):
    org_id: str


class ForcePublishJobCreatedResponse(BaseModel):
    """Returned from POST /ingest/org/force-publish when a job is kicked off
    (201) or when an in-flight job already exists for the org (409 — caller
    receives the existing job_id rather than spawning a duplicate)."""
    job_id: str
    org_id: str
    status: str = Field(..., pattern=r"^(pending|running)$")
    already_running: bool = False


class ForcePublishJobStatusResponse(BaseModel):
    job_id: str
    org_id: str
    status: str = Field(..., pattern=r"^(pending|running|completed|failed|partial)$")
    scanned: int = 0
    published: int = 0
    batches: int = 0
    errors: list[str] = Field(default_factory=list)
    error_message: str | None = None
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class OrgIngestJobCreatedResponse(BaseModel):
    """Returned from POST /ingest/org/async when a job is kicked off (202)
    or when an in-flight job already exists for the org (409 — caller
    receives the existing job_id rather than spawning a duplicate)."""
    job_id: str
    org_id: str
    status: str = Field(..., pattern=r"^(pending|running)$")
    already_running: bool = False


class OrgIngestJobStatusResponse(BaseModel):
    job_id: str
    org_id: str
    status: str = Field(..., pattern=r"^(pending|running|completed|failed|partial)$")
    current_event_type: str | None = None
    events_total: int = 0
    events_processed: int = 0
    events_skipped: int = 0
    nodes_created: int = 0
    edges_created: int = 0
    errors_count: int = 0
    event_counts: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    error_message: str | None = None
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
