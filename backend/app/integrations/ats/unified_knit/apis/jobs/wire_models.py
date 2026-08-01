"""Pydantic mirrors of Knit's unified job wire shapes (camelCase via alias
generator, extra ignored so Knit additions never break parsing)."""

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _Wire(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="ignore"
    )


class KnitJobInfo(_Wire):
    id: str
    title: str
    description: str | None = None
    status: str = "NOT_SPECIFIED"
    created_at: str | None = None
    updated_at: str | None = None
    info_url: str | None = None
    apply_url: str | None = None


class KnitNamedRef(_Wire):
    id: str | None = None
    name: str | None = None


class KnitOffice(_Wire):
    id: str | None = None
    name: str | None = None
    location: str | None = None


class KnitUserRef(_Wire):
    id: str | None = None
    email: str | None = None
    employee_id: str | None = None


class KnitStage(_Wire):
    id: str | None = None
    text: str | None = None


class KnitJob(_Wire):
    """Collections are Optional: Workable-via-Knit sends explicit null for
    empty departments/offices/managers/recruiters/stages (live-verified
    2026-06-11). Mapping normalizes None → []."""

    info: KnitJobInfo
    departments: list[KnitNamedRef] | None = None
    offices: list[KnitOffice] | None = None
    hiring_managers: list[KnitUserRef] | None = None
    recruiters: list[KnitUserRef] | None = None
    stages: list[KnitStage] | None = None


class KnitListJobsData(_Wire):
    jobs: list[KnitJob] | None = None
    next_page_token: str | None = None
