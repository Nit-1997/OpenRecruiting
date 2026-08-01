from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStage(str, Enum):
    FETCH_DATA = "fetch_data"
    CHUNK_INTERVIEW = "chunk_interview"
    MAP_TOPICS = "map_topics"
    EXTRACT_FEEDBACK = "extract_feedback"
    CONDENSE_FEEDBACK = "condense_feedback"
    EXTRACT_EVIDENCE = "extract_evidence"
    JUDGE_FEEDBACK = "judge_feedback"
    PERSIST_RESULTS = "persist_results"


class Job(BaseModel):
    id: str
    candidate_round_id: str
    status: JobStatus = JobStatus.PENDING
    current_stage: JobStage | None = None

    chunk_map: dict | None = None
    topic_map: dict | None = None
    topic_chunk_map: dict | None = None
    topic_feedback_map: dict | None = None
    enriched_feedback: list | None = None
    judged_feedback: list | None = None

    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    retry_count: int = 0
