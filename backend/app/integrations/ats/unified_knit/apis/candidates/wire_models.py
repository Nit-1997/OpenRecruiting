"""Pydantic mirrors of Knit's unified candidate/application wire shapes.
Knit's real payloads are null-heavy (links/owner/interviews arrive as null,
not absent) — every collection is Optional and normalized in mapping."""

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _Wire(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="ignore"
    )


class KnitPhone(_Wire):
    type: str | None = None
    phone_number: str | None = None


class KnitEmail(_Wire):
    type: str | None = None
    email: str | None = None


class KnitCandidate(_Wire):
    id: str
    first_name: str | None = None
    last_name: str | None = None
    phones: list[KnitPhone] | None = None
    emails: list[KnitEmail] | None = None
    links: list[str] | None = None
    location: str | None = None


class KnitApplicationInfo(_Wire):
    id: str
    status: str = "NOT_SPECIFIED"
    candidate: KnitCandidate
    applied_at: str | None = None
    updated_at: str | None = None
    job_id: str | None = None


class KnitStageRef(_Wire):
    id: str | None = None
    text: str | None = None


class KnitRejection(_Wire):
    id: str | None = None
    text: str | None = None
    rejected_at: str | None = None


class KnitAttachment(_Wire):
    type: str | None = None       # RESUME | COVER_LETTER | ...
    name: str | None = None
    link: str | None = None       # presigned (expiring) download URL


class KnitAnswer(_Wire):
    text: str | None = None
    selected_option: str | None = None
    selected_options: list[str] | None = None
    number_value: float | None = None
    date_value: str | None = None
    rating_value: float | None = None


class KnitQuestionResponse(_Wire):
    question_text: str | None = None
    question_type: str | None = None   # YES_NO | FREE_TEXT | ...
    answer: KnitAnswer | None = None


class KnitApplication(_Wire):
    info: KnitApplicationInfo
    current_stage: KnitStageRef | None = None
    rejection: KnitRejection | None = None
    attachments: list[KnitAttachment] | None = None
    question_responses: list[KnitQuestionResponse] | None = None


class KnitListApplicationsData(_Wire):
    applications: list[KnitApplication] = Field(default_factory=list)
    next_page_token: str | None = None
