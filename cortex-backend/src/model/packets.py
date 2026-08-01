from dataclasses import dataclass, field


@dataclass
class CandidateRoundData:
    id: str
    candidate_id: str
    round_id: str
    requisition_id: str
    rating: str | None = None
    interviewer_email: str | None = None
    interviewer_name: str | None = None
    organization_id: str | None = None


@dataclass
class RoundData:
    id: str
    name: str
    requisition_id: str
    category: str | None = None
    duration_minutes: int | None = None
    skills: list[str] = field(default_factory=list)


@dataclass
class RequisitionData:
    id: str
    role_title: str
    organization_id: str
    organization_name: str | None = None
    organization_domain: str | None = None
    status: str | None = None
    experience_min_years: int | None = None
    experience_max_years: int | None = None
    role_location: str | None = None
    must_have_skills: list[str] = field(default_factory=list)
    nice_to_have_skills: list[str] = field(default_factory=list)


@dataclass
class CandidateData:
    id: str
    name: str
    organization_id: str
    status: str | None = None


@dataclass
class FeedbackItemData:
    heading: str
    question_id: str | None = None
    feedback_text: str | None = None
    evidence: list[str] = field(default_factory=list)
    evidence_status: str | None = None


@dataclass
class RoundWithCompetenciesData:
    id: str
    name: str
    category: str | None = None
    duration_minutes: int | None = None
    skills: list[str] = field(default_factory=list)
    competency_headings: list[str] = field(default_factory=list)
    order: int | None = None


@dataclass
class FeedbackPacket:
    candidate_round: CandidateRoundData
    round: RoundData
    requisition: RequisitionData
    candidate: CandidateData
    feedback_items: list[FeedbackItemData] = field(default_factory=list)


@dataclass
class PlanPacket:
    requisition: RequisitionData
    rounds: list[RoundWithCompetenciesData] = field(default_factory=list)


@dataclass
class DecisionPacket:
    candidate: CandidateData
    requisition: RequisitionData


@dataclass
class EpisodicMetadata:
    candidate_round_id: str
    candidate_id: str
    candidate_name: str
    round_id: str
    round_name: str
    round_category: str | None
    requisition_id: str
    role_title: str
    organization_id: str
    interviewer_email: str | None = None
    interviewer_ref: str | None = None
    interviewer_name: str | None = None


@dataclass
class IntakeMetadata:
    requisition_id: str
    role_title: str
    organization_id: str


from pydantic import BaseModel
from typing import Any


class IntakeV2Packet(BaseModel):
    """Structured input for IntakeV2Handler. Populated by SupabaseFetcher.fetch_intake_v2_session."""

    session_id: str
    requisition_id: str
    organization_id: str
    user_id: str | None = None

    role_title: str
    role_location: str | None = None
    experience_min_years: int | None = None
    experience_max_years: int | None = None

    form_data: dict[str, Any]
    current_answers: dict[str, Any]
    turns: list[dict[str, Any]]
    modalities_used: list[str]
    duration_min: float | None = None
    questions_version: str | None = None
    interview_plan: dict[str, Any] | None = None

    rounds: list[dict[str, Any]] = []
