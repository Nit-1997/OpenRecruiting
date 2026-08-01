"""Canonical job models. Shapes follow Knit's unified ATS model (already a
cross-ATS normalization); statuses stay plain strings so unknown provider
values never break parsing. Known job statuses: OPEN, CLOSED, DRAFT,
NOT_SPECIFIED."""

from pydantic import BaseModel, Field


class AtsDepartment(BaseModel):
    id: str | None = None
    name: str | None = None


class AtsOffice(BaseModel):
    id: str | None = None
    name: str | None = None
    location: str | None = None


class AtsTeamMember(BaseModel):
    id: str | None = None
    email: str | None = None


class AtsStage(BaseModel):
    id: str | None = None
    name: str | None = None


class AtsJob(BaseModel):
    id: str
    title: str
    status: str
    description: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    info_url: str | None = None
    apply_url: str | None = None
    departments: list[AtsDepartment] = Field(default_factory=list)
    offices: list[AtsOffice] = Field(default_factory=list)
    hiring_managers: list[AtsTeamMember] = Field(default_factory=list)
    recruiters: list[AtsTeamMember] = Field(default_factory=list)
    stages: list[AtsStage] = Field(default_factory=list)


class AtsJobCreate(BaseModel):
    """Phase-1 minimal create payload (port member only — no HTTP route)."""

    title: str
    description: str | None = None
    status: str | None = None
