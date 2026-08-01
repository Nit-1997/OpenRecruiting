from pydantic import BaseModel

from .pydantic_models import (
    ChunkContent,
    ChunkData,
    EnrichedFeedbackItem,
    FeedbackItem,
    JudgedFeedbackItem,
    ParticipantDetection,
    QuestionSummary,
    RoleContext,
    TopicFeedbackResult,
    TopicInfo,
    TopicMapping,
)


class TopicMappingResponse(BaseModel):
    transcript_metadata: dict
    participants: ParticipantDetection
    chunks: list[ChunkData]
    topic_mappings: list[TopicMapping]
    warnings: list[str] = []


class FeedbackProcessingResponse(BaseModel):
    topic_feedback: list[TopicFeedbackResult]
    debug_extracted_bullets: dict[str, list[str]] | None = None


class CompleteProcessingResponse(BaseModel):
    chunk_map: dict[str, ChunkContent]
    topic_map: dict[str, TopicInfo]
    topic_chunk_map: dict[str, list[str]]
    topic_feedback_map: dict[str, list[FeedbackItem]]


class EvidenceExtractionResponse(BaseModel):
    enriched_feedback: list[EnrichedFeedbackItem]


class JudgeResponse(BaseModel):
    judged_feedback: list[JudgedFeedbackItem]
    role_context_used: RoleContext | None = None


class SummaryResponse(BaseModel):
    question_summaries: list[QuestionSummary]
    round_summary: str
    competency_snapshots: str
    round_rating: str
    overall_feedback: list[dict] = []


class JobResponse(BaseModel):
    candidate_round_id: str
    status: str
    message: str = ""
