from typing import Optional, Literal

from pydantic import BaseModel


class InterviewedInEdge(BaseModel):
    rating: Optional[Literal["strong_yes", "yes", "maybe", "no", "strong_no"]] = None


class CompetencyEdge(BaseModel):
    evidence_status: Literal["from_rating", "per_item", "supported", "unsupported"] = "from_rating"
    feedback_text: Optional[str] = None
    evidence: Optional[list[str]] = None
    round_rating: Optional[Literal["strong_yes", "yes", "maybe", "no", "strong_no"]] = None
    weight: Optional[float] = None


class ConductedEdge(BaseModel):
    pass


class HasRoundEdge(BaseModel):
    order: Optional[int] = None


class AssessesEdge(BaseModel):
    pass


class LocatedInEdge(BaseModel):
    pass


class RequiresEdge(BaseModel):
    pass


class NiceToHaveEdge(BaseModel):
    pass


class DecisionEdge(BaseModel):
    pass


class AppliedToEdge(BaseModel):
    """Baseline pipeline membership: a candidate is in a requisition's pipeline,
    independent of any hire/reject outcome. Emitted for EVERY candidate so the
    graph models the applicant pool, not just decided candidates."""
    stage: Optional[str] = None
    status: Optional[str] = None
    applied_at: Optional[str] = None
    source: Optional[str] = None


class WorkedAtEdge(BaseModel):
    role_title: Optional[str] = None
    duration: Optional[str] = None
    what_they_built: Optional[str] = None
    achievement: Optional[str] = None
    seniority_signal: Optional[str] = None


class ExhibitsEdge(BaseModel):
    evidence: Optional[str] = None
    source: Optional[Literal["interview", "feedback", "summary", "question_summary", "intake"]] = None
    confidence: Optional[Literal["high", "medium", "low"]] = None
    weight: Optional[float] = None


class ExperiencedInEdge(BaseModel):
    depth: Optional[Literal["deep", "moderate", "exposure"]] = None
    evidence: Optional[str] = None
    geographic_scope: Optional[str] = None


class ValuesEdge(BaseModel):
    priority: Optional[Literal["must_have", "nice_to_have", "implicit"]] = None
    evidence: Optional[str] = None


class DemonstratesEdge(BaseModel):
    evidence: Optional[str] = None
    pattern_frequency: Optional[Literal["consistent", "occasional", "one_time"]] = None
    weight: Optional[float] = None


class OperatesInEdge(BaseModel):
    role: Optional[Literal["primary", "secondary", "expanding_into"]] = None


class HasCultureEdge(BaseModel):
    evidence: Optional[str] = None
    source: Optional[Literal["intake", "jd", "interview"]] = None


class TargetsEdge(BaseModel):
    pass


class KnownForEdge(BaseModel):
    pass


class BasedInEdge(BaseModel):
    pass


class ClaimedEdge(BaseModel):
    evidence: Optional[str] = None


class DemonstratedSkillEdge(BaseModel):
    evidence: Optional[str] = None
    weight: Optional[float] = None


class EvaluatedEdge(BaseModel):
    pass


class HostsEdge(BaseModel):
    pass


EDGE_MODELS: dict[str, type[BaseModel]] = {
    "INTERVIEWED_IN": InterviewedInEdge,
    "STRONG_IN": CompetencyEdge,
    "WEAK_IN": CompetencyEdge,
    "ASSESSED_ON": CompetencyEdge,
    "CONDUCTED": ConductedEdge,
    "HAS_ROUND": HasRoundEdge,
    "ASSESSES": AssessesEdge,
    "LOCATED_IN": LocatedInEdge,
    "REQUIRES": RequiresEdge,
    "NICE_TO_HAVE": NiceToHaveEdge,
    "HIRED_BY": DecisionEdge,
    "REJECTED_BY": DecisionEdge,
    "WITHDREW_FROM": DecisionEdge,
    "APPLIED_TO": AppliedToEdge,
    "WORKED_AT": WorkedAtEdge,
    "EXHIBITS": ExhibitsEdge,
    "EXPERIENCED_IN": ExperiencedInEdge,
    "VALUES": ValuesEdge,
    "DEMONSTRATES": DemonstratesEdge,
    "OPERATES_IN": OperatesInEdge,
    "HAS_CULTURE": HasCultureEdge,
    "TARGETS": TargetsEdge,
    "KNOWN_FOR": KnownForEdge,
    "BASED_IN": BasedInEdge,
    "CLAIMED": ClaimedEdge,
    "DEMONSTRATED": DemonstratedSkillEdge,
    "EVALUATED": EvaluatedEdge,
    "HOSTS": HostsEdge,
}

EDGE_TYPE_MAP: dict[tuple[str, str], list[str]] = {
    ("Candidate", "Round"): ["INTERVIEWED_IN"],
    ("Candidate", "Competency"): ["STRONG_IN", "WEAK_IN", "ASSESSED_ON"],
    ("Candidate", "Requisition"): ["HIRED_BY", "REJECTED_BY", "WITHDREW_FROM", "APPLIED_TO"],
    ("Interviewer", "Round"): ["CONDUCTED"],
    ("Requisition", "Round"): ["HAS_ROUND"],
    ("Round", "Skill"): ["ASSESSES"],
    ("Round", "Competency"): ["ASSESSES"],
    ("Requisition", "Location"): ["LOCATED_IN"],
    ("Requisition", "Skill"): ["REQUIRES", "NICE_TO_HAVE"],
    ("Organization", "Requisition"): ["HOSTS"],
    # -- Episodic ingestion (new) --
    ("Candidate", "Company"): ["WORKED_AT"],
    ("Candidate", "Skill"): ["DEMONSTRATED", "CLAIMED"],
    ("Candidate", "Trait"): ["EXHIBITS"],
    ("Candidate", "Market"): ["EXPERIENCED_IN"],
    ("Candidate", "Location"): ["BASED_IN"],
    ("Requisition", "Market"): ["TARGETS"],
    ("Requisition", "Trait"): ["VALUES"],
    ("Interviewer", "Trait"): ["DEMONSTRATES"],
    ("Interviewer", "Candidate"): ["EVALUATED"],
    ("Company", "Skill"): ["KNOWN_FOR"],
    ("Company", "Market"): ["OPERATES_IN"],
    ("Company", "Location"): ["BASED_IN"],
    ("Company", "Trait"): ["HAS_CULTURE"],
}
