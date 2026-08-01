from pydantic import BaseModel


class TopicInput(BaseModel):
    heading: str
    description: str


class ChunkData(BaseModel):
    id: int
    time_range: str
    primary_speaker: str
    speakers: list[str]
    token_count: int
    content: str


class ChunkContent(BaseModel):
    time_range: str
    speaker: str
    content: str


class TopicInfo(BaseModel):
    heading: str
    description: str


class TopicMapping(BaseModel):
    topic_id: str
    heading: str
    description: str
    relevant_chunk_ids: list[int]
    relevant_chunks: list[ChunkData]
    reasoning: str


class ParticipantDetection(BaseModel):
    candidate: str
    interviewer: str
    auto_detected: bool
    confidence: str | None = None
    reasoning: str | None = None


class FeedbackBullet(BaseModel):
    feedback_bullet: str
    antifeedback_bullet: str
    sentiment: str = "neutral"
    source_context: str = ""   # NEW
    claim_strength: str = "primary"   # NEW


class TopicFeedbackResult(BaseModel):
    topic_id: str
    heading: str
    description: str
    raw_bullets: list[str]
    condensed_feedback: list[FeedbackBullet]


class FeedbackItem(BaseModel):
    feedback: str
    antifeedback: str
    sentiment: str
    source_context: str = ""   # NEW
    claim_strength: str = "primary"   # NEW


class EnrichedFeedbackItem(BaseModel):
    topic_id: str
    topic_heading: str
    feedback: str
    antifeedback: str
    sentiment: str
    feedback_evidence: list[str]
    antifeedback_evidence: list[str]
    reasoning: str
    source_context: str = ""   # NEW
    claim_strength: str = "primary"   # NEW


class RoleContext(BaseModel):
    role_title: str = "Product Manager"
    experience_range: str = "3-6 years"
    must_have_skills: list[str] = []
    good_to_have_skills: list[str] = []
    job_description: str = ""
    intake_notes: str = ""


class JudgedFeedbackItem(BaseModel):
    topic_id: str
    topic_heading: str
    feedback: str
    sentiment: str
    evidence_status: str
    evidence: list[str]
    reasoning: str
    claim_strength: str = "primary"   # NEW


class QuestionSummary(BaseModel):
    topic_id: str
    topic_heading: str
    summary: str
    evidence_status: str
    sentiment: str


class SummaryResult(BaseModel):
    question_summaries: list[QuestionSummary]
    round_summary: str
    competency_snapshots: str
    round_rating: str
    overall_feedback: list[dict] = []
