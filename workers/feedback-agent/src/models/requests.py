from pydantic import BaseModel

from .pydantic_models import (
    ChunkContent,
    EnrichedFeedbackItem,
    FeedbackItem,
    RoleContext,
    TopicInfo,
    TopicInput,
)


class TopicMappingRequest(BaseModel):
    transcript: str
    candidate_name: str | None = None
    topics: list[TopicInput]


class FeedbackProcessingRequest(BaseModel):
    transcript: str
    topics: list[TopicInput]


class CompleteProcessingRequest(BaseModel):
    interview_transcript: str
    feedback_transcript: str
    topics: list[TopicInput]
    candidate_name: str | None = None


class EvidenceExtractionRequest(BaseModel):
    chunk_map: dict[str, ChunkContent]
    topic_map: dict[str, TopicInfo]
    topic_chunk_map: dict[str, list[str]]
    topic_feedback_map: dict[str, list[FeedbackItem]]


class JudgeRequest(BaseModel):
    enriched_feedback: list[EnrichedFeedbackItem]
    role_context: RoleContext | None = None


class JobRequest(BaseModel):
    candidate_round_id: str
