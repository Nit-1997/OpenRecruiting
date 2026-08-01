"""Canonical candidate/application models. Known application statuses:
ACTIVE, REJECTED, HIRED, NOT_SPECIFIED (kept as plain strings)."""

from pydantic import BaseModel, Field


class AtsContactPoint(BaseModel):
    type: str | None = None
    value: str


class AtsCandidate(BaseModel):
    id: str
    first_name: str | None = None
    last_name: str | None = None
    emails: list[AtsContactPoint] = Field(default_factory=list)
    phones: list[AtsContactPoint] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    location: str | None = None
    position: str | None = None
    company: str | None = None
    school: str | None = None
    social_links: list[str] = Field(default_factory=list)


class AtsStageRef(BaseModel):
    id: str | None = None
    name: str | None = None


class AtsRejection(BaseModel):
    id: str | None = None
    reason: str | None = None
    rejected_at: str | None = None


class AtsAttachment(BaseModel):
    type: str | None = None       # RESUME | COVER_LETTER | ...
    name: str | None = None
    url: str | None = None        # presigned (expiring) download URL


class AtsQuestionResponse(BaseModel):
    question: str | None = None
    type: str | None = None
    answer: str | None = None     # normalized from the typed answer object


class AtsApplication(BaseModel):
    id: str
    status: str
    candidate: AtsCandidate
    job_id: str | None = None
    applied_at: str | None = None
    updated_at: str | None = None
    current_stage: AtsStageRef | None = None
    rejection: AtsRejection | None = None
    attachments: list[AtsAttachment] = Field(default_factory=list)
    question_responses: list[AtsQuestionResponse] = Field(default_factory=list)


class CandidateSearchCriteria(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None

    def is_empty(self) -> bool:
        return not any((self.first_name, self.last_name, self.email, self.phone))
