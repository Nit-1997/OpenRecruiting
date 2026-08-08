from typing import Optional, Literal

from pydantic import BaseModel


class SkillEntity(BaseModel):
    name: str
    category: Optional[str] = None
    aliases: Optional[list[str]] = None


class RequisitionEntity(BaseModel):
    role_title: str
    # Mirrors requisitions_status_check in schema.sql — the DB constraint is the
    # authority. A value it cannot store ("active") only parks events at the
    # attempt cap; a value it does store ("draft") must be accepted here.
    status: Optional[Literal["draft", "intake_pending", "planned", "closed"]] = None
    experience_min_years: Optional[int] = None
    experience_max_years: Optional[int] = None
    role_location: Optional[str] = None


class RoundEntity(BaseModel):
    name: str
    category: Optional[str] = None
    duration_minutes: Optional[int] = None


class CompetencyEntity(BaseModel):
    heading: str


class CandidateEntity(BaseModel):
    name: str
    candidate_ref: str
    status: Optional[Literal["active", "hired", "rejected", "withdrawn"]] = None


class InterviewerEntity(BaseModel):
    interviewer_ref: str


class LocationEntity(BaseModel):
    name: str
    location_type: Optional[Literal["city", "region", "country", "remote"]] = None
    aliases: Optional[list[str]] = None


class CompanyEntity(BaseModel):
    name: str
    size_signal: Optional[Literal["startup", "scaleup", "enterprise", "unknown"]] = None
    domain_summary: Optional[str] = None
    aliases: Optional[list[str]] = None


class TraitEntity(BaseModel):
    name: str
    category: Optional[str] = None
    polarity: Optional[str] = None
    aliases: Optional[list[str]] = None


class MarketEntity(BaseModel):
    name: str
    category: Optional[str] = None
    aliases: Optional[list[str]] = None


class OrganizationEntity(BaseModel):
    name: str
    organization_ref: str
    domain: Optional[str] = None


ENTITY_TYPES: dict[str, type[BaseModel]] = {
    "Skill": SkillEntity,
    "Requisition": RequisitionEntity,
    "Round": RoundEntity,
    "Competency": CompetencyEntity,
    "Candidate": CandidateEntity,
    "Interviewer": InterviewerEntity,
    "Location": LocationEntity,
    "Company": CompanyEntity,
    "Trait": TraitEntity,
    "Market": MarketEntity,
    "Organization": OrganizationEntity,
}
