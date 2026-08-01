from pydantic import BaseModel, Field, validator, field_validator
from typing import Optional, List, Dict
from uuid import UUID
from datetime import datetime
from .enums import EvidenceStatus, RoundRating


# ============================================
# REQUISITION MODELS
# ============================================

class RequisitionCreate(BaseModel):
    role_title: str = Field(..., min_length=1, max_length=255)
    role_location: str = Field(..., min_length=1, max_length=255)
    experience_min_years: int = Field(default=0, ge=0)
    experience_max_years: Optional[int] = Field(default=None, ge=0)


class RequisitionUpdate(BaseModel):
    role_title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    role_location: Optional[str] = Field(default=None, min_length=1, max_length=255)
    experience_min_years: Optional[int] = Field(default=None, ge=0)
    experience_max_years: Optional[int] = Field(default=None, ge=0)


class IntakeUpdate(BaseModel):
    intake_notes: Optional[str] = None
    job_description: Optional[str] = None
    must_have_skills: Optional[List[str]] = None
    good_to_have_skills: Optional[List[str]] = None


class RequisitionResponse(BaseModel):
    id: UUID
    organization_id: UUID
    created_by: Optional[UUID] = None
    role_title: str
    role_location: str
    experience_min_years: int
    experience_max_years: Optional[int]
    experience_display: str
    status: str
    intake_notes: Optional[str] = None
    job_description: Optional[str] = None
    must_have_skills: List[str] = []
    good_to_have_skills: List[str] = []
    intake_transcript: Optional[str] = None
    intake_processing_status: Optional[str] = None
    intake_processing_error: Optional[str] = None
    intake_voice_session_token: Optional[str] = None
    intake_voice_session_status: Optional[str] = None
    auto_join_untracked: Optional[bool] = None
    created_at: datetime
    updated_at: datetime


class RequisitionListResponse(BaseModel):
    requisitions: List[RequisitionResponse]
    total: int


# ============================================
# FEEDBACK QUESTION MODELS
# ============================================

class FeedbackQuestionInput(BaseModel):
    heading: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None

    class Config:
        extra = "ignore"


class FeedbackQuestionCreate(BaseModel):
    heading: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None


class FeedbackQuestionUpdate(BaseModel):
    heading: Optional[str] = Field(default=None, min_length=1, max_length=500)
    description: Optional[str] = None


class FeedbackQuestionResponse(BaseModel):
    id: UUID
    round_id: UUID
    question_number: int
    heading: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ============================================
# ROUND MODELS
# ============================================

class GuidelineInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None


class RoundInput(BaseModel):
    name: Optional[str] = Field(default="Untitled Round", max_length=255)
    category: Optional[str] = None
    duration_minutes: Optional[int] = Field(default=45, ge=0, le=480)
    description: Optional[str] = None
    summary: Optional[str] = None
    rating: Optional[str] = None
    skills: Optional[List[str]] = Field(default_factory=list)
    guidelines: Optional[List[GuidelineInput]] = Field(default_factory=list)
    feedback_questions: Optional[List[FeedbackQuestionInput]] = Field(default_factory=list)
    round_type: Optional[str] = Field(default="interview")
    assessment_template_id: Optional[UUID] = None
    default_interviewer_emails: Optional[List[str]] = Field(default_factory=list)

    class Config:
        extra = "ignore"

    @validator('name', pre=True, always=True)
    def name_default(cls, v):
        return v if v and str(v).strip() else "Untitled Round"

    @validator('duration_minutes', pre=True, always=True)
    def duration_default(cls, v):
        if v is None or v == "":
            return 45
        try:
            return int(v)
        except (ValueError, TypeError):
            return 45

    @validator('skills', 'guidelines', 'feedback_questions', pre=True, always=True)
    def list_default(cls, v):
        return v if v else []

    @validator('rating', pre=True, always=True)
    def rating_enum_check(cls, v):
        if v is None or v == "":
            return None
        valid_ratings = [r.value for r in RoundRating]
        return v if v in valid_ratings else None


class RoundCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    category: Optional[str] = Field(default=None, max_length=50)
    duration_minutes: int = Field(default=45, gt=0, le=480)
    description: Optional[str] = None
    skills: List[str] = []
    round_type: Optional[str] = Field(default="interview")
    assessment_template_id: Optional[UUID] = None
    default_interviewer_emails: List[str] = []


class RoundUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    category: Optional[str] = Field(default=None, max_length=50)
    duration_minutes: Optional[int] = Field(default=None, gt=0, le=480)
    description: Optional[str] = None
    skills: Optional[List[str]] = None
    round_type: Optional[str] = None
    assessment_template_id: Optional[UUID] = None
    default_interviewer_emails: Optional[List[str]] = None


class RoundResponse(BaseModel):
    id: UUID
    requisition_id: UUID
    round_number: int
    name: str
    category: Optional[str] = None
    duration_minutes: int
    duration_display: str
    description: Optional[str] = None
    skills: List[str] = []
    guidelines: List[dict] = []
    round_type: Optional[str] = "interview"
    assessment_template_id: Optional[UUID] = None
    default_interviewer_emails: List[str] = []
    created_at: datetime
    updated_at: datetime


class RoundWithQuestionsResponse(RoundResponse):
    feedback_questions: List[FeedbackQuestionResponse] = []
    assessment_template: Optional[dict] = None


class RoundOrderItem(BaseModel):
    round_id: UUID
    round_number: int


class RoundReorderRequest(BaseModel):
    round_orders: List[RoundOrderItem]


# ============================================
# INTERVIEW PLAN MODELS (Bulk Operations)
# ============================================

class InterviewPlanCreate(BaseModel):
    rounds: List[RoundInput]


class InterviewPlanResponse(BaseModel):
    requisition_id: UUID
    total_rounds: int
    total_duration_minutes: int
    total_duration_display: str
    rounds: List[RoundWithQuestionsResponse]


class RequisitionWithPlanResponse(RequisitionResponse):
    plan: Optional[InterviewPlanResponse] = None


# ============================================
# CANDIDATE MODELS (For future use)
# ============================================

class CandidateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=1, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=50)
    resume_url: Optional[str] = None


class CandidateResponse(BaseModel):
    id: UUID
    requisition_id: UUID
    name: str
    email: str
    phone: Optional[str] = None
    resume_url: Optional[str] = None
    status: str
    final_verdict: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CandidateListResponse(BaseModel):
    candidates: List[CandidateResponse]
    total: int


# ============================================
# CANDIDATE ROUND MODELS
# ============================================

class CandidateRoundResponse(BaseModel):
    id: UUID
    candidate_id: UUID
    round_id: UUID
    round_name: str
    round_number: int
    status: str
    scheduled_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    outcome: Optional[str] = None
    outcome_notes: Optional[str] = None
    bot_session_id: Optional[str] = None
    transcript_url: Optional[str] = None
    recording_url: Optional[str] = None
    meeting_url: Optional[str] = None
    interviewer_email: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    round_type: Optional[str] = "interview"
    can_reschedule: Optional[bool] = None


class CandidateFeedbackResponse(BaseModel):
    id: Optional[UUID] = None
    feedback_question_id: UUID
    heading: str
    question_number: int
    feedback_text: Optional[str] = None
    evidence: List[str] = Field(default_factory=list)
    evidence_status: Optional[str] = None
    source: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class FeedbackEntryResponse(BaseModel):
    id: Optional[UUID] = None
    feedback_data: Optional[str] = None
    evidence: List[str] = Field(default_factory=list)
    evidence_status: Optional[str] = None
    source: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class FeedbackQuestionWithFeedbackResponse(BaseModel):
    id: UUID
    question_number: int
    heading: str
    description: Optional[str] = None
    feedback: List[FeedbackEntryResponse] = Field(default_factory=list)
    summary: Optional[str] = None


class CandidateRoundDetailResponse(CandidateRoundResponse):
    round_category: Optional[str] = None
    round_duration_minutes: int = 0
    round_description: Optional[str] = None
    summary: Optional[str] = None
    rating: Optional[str] = None
    feedback_questions: List[FeedbackQuestionWithFeedbackResponse] = Field(default_factory=list)
    round_type: Optional[str] = None
    assessment_template: Optional[dict] = None
    assessment_instance: Optional[dict] = None
    processing_status: Optional[str] = None
    feedback_approved_at: Optional[datetime] = None
    feedback_approved_by_email: Optional[str] = None


class CandidateWithRoundsResponse(CandidateResponse):
    rounds: List[CandidateRoundResponse] = []


class CandidateHiringPacketResponse(CandidateResponse):
    requisition_title: str
    rounds: List[CandidateRoundDetailResponse] = []
    overall_progress: str
    overall_average_rating: Optional[float] = None


class CandidateWithRoundsListResponse(BaseModel):
    candidates: List[CandidateWithRoundsResponse]
    total: int


# ============================================
# CANDIDATE REQUEST MODELS
# ============================================

class CandidateStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(active|hired|rejected|withdrawn)$")
    final_verdict: Optional[str] = Field(default=None, pattern="^(strong_hire|hire|no_hire|strong_no_hire)$")


class ScheduleInterviewRequest(BaseModel):
    scheduled_at: datetime
    meeting_url: Optional[str] = Field(default=None, min_length=1, description="Meeting URL (required for interviews, optional for assessments)")
    interviewer_email: Optional[str] = Field(
        default=None,
        pattern=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",
        description="Optional - for feedback reminders"
    )
    scheduling_timezone: Optional[str] = Field(
        default=None,
        description="IANA timezone string used when scheduling (e.g., America/New_York)"
    )

    @field_validator("scheduled_at")
    @classmethod
    def scheduled_at_must_be_aware(cls, v):
        if v.tzinfo is None:
            raise ValueError("scheduled_at must include timezone offset (e.g. 2026-04-01T10:00:00+05:30)")
        return v


class RoundOutcomeUpdate(BaseModel):
    outcome: str = Field(..., pattern="^(advance|reject|hold)$")
    outcome_notes: Optional[str] = None
    completed_at: Optional[datetime] = None


class FeedbackItemInput(BaseModel):
    id: Optional[UUID] = None  # If provided, update this specific feedback row; otherwise insert new
    feedback_question_id: UUID
    feedback_text: Optional[str] = None


class SubmitFeedbackRequest(BaseModel):
    feedback: List[FeedbackItemInput]
    source: str = Field(default="manual", pattern="^(manual|bot)$")


class StructuredFeedbackInput(BaseModel):
    id: Optional[UUID] = None
    feedback_question_id: UUID
    feedback_data: Optional[str] = ""
    evidence: Optional[List[str]] = Field(default_factory=list)
    evidence_status: Optional[str] = None

    class Config:
        extra = "ignore"

    @validator('feedback_data', pre=True, always=True)
    def feedback_default(cls, v):
        return v if v else ""

    @validator('evidence', pre=True, always=True)
    def evidence_default(cls, v):
        return v if v else []

    @validator('evidence_status', pre=True, always=True)
    def status_enum_check(cls, v):
        if v is None or v == "":
            return None
        valid_statuses = [s.value for s in EvidenceStatus]
        return v if v in valid_statuses else None


class SubmitStructuredFeedbackRequest(BaseModel):
    feedback: List[StructuredFeedbackInput]
    round_summary: Optional[str] = None
    round_rating: Optional[str] = None
    source: str = Field(default="manual", pattern="^(manual|bot)$")

    class Config:
        extra = "ignore"

    @validator('round_rating', pre=True, always=True)
    def rating_enum_check(cls, v):
        if v is None or v == "":
            return None
        valid_ratings = [r.value for r in RoundRating]
        return v if v in valid_ratings else None


class SubmitFeedbackResponse(BaseModel):
    candidate_round_id: UUID
    feedback: List[CandidateFeedbackResponse]
    total_submitted: int


# ============================================
# DEBRIEF MODELS
# ============================================

class DebriefRoundInfo(BaseModel):
    id: UUID
    name: str
    round_number: int
    round_type: Optional[str] = "interview"


class DebriefRoundRating(BaseModel):
    candidate_round_id: UUID
    rating: Optional[str] = None
    status: str
    summary: Optional[str] = None
    processing_status: Optional[str] = None


class DebriefCandidate(BaseModel):
    id: UUID
    name: str
    email: str
    status: str
    final_verdict: Optional[str] = None
    avg_rating: Optional[float] = None
    rank: int
    round_ratings: Dict[str, DebriefRoundRating]
    ai_summary: Optional[str] = None


class DebriefResponse(BaseModel):
    requisition_id: UUID
    requisition_title: str
    rounds: List[DebriefRoundInfo]
    candidates: List[DebriefCandidate]
    ai_insights: Optional[Dict] = None


class DebriefInsightsResponse(BaseModel):
    generated_at: str
    candidates: Dict[str, str]
    ranking_rationale: str


# ============================================
# HELPER FUNCTIONS
# ============================================

def format_experience(min_years: int, max_years: Optional[int]) -> str:
    if max_years is None:
        return f"{min_years}+ years"
    elif min_years == max_years:
        return f"{min_years} years"
    else:
        return f"{min_years}-{max_years} years"


def format_duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} mins"
    hours = minutes // 60
    remaining_mins = minutes % 60
    if remaining_mins == 0:
        return f"{hours} hr" if hours == 1 else f"{hours} hrs"
    return f"{hours} hr {remaining_mins} mins" if hours == 1 else f"{hours} hrs {remaining_mins} mins"


# ============================================
# SAMPLE INTERVIEW PLAN
# ============================================

SAMPLE_INTERVIEW_PLAN = {
    "rounds": [
        {
            "name": "Problem Solving",
            "category": "coding",
            "duration_minutes": 45,
            "description": "Evaluate algorithmic thinking and coding skills through DSA problems",
            "skills": ["Data Structures", "Algorithms", "Problem Decomposition", "Code Quality"],
            "guidelines": [
                {"title": "Start with problem clarification", "description": "Ensure candidate asks clarifying questions about constraints and edge cases"},
                {"title": "Evaluate approach before coding", "description": "Have candidate explain their approach before writing code"},
                {"title": "Assess time and space complexity", "description": "Ask candidate to analyze complexity of their solution"}
            ],
            "feedback_questions": [
                {"heading": "Problem Decomposition", "description": "Candidate's ability to break down complex problems into manageable parts"},
                {"heading": "Code Quality", "description": "Readability, structure, and maintainability of the code written"},
                {"heading": "Edge Case Handling", "description": "Identification and handling of boundary conditions and edge cases"},
                {"heading": "Communication", "description": "Clarity in explaining thought process and approach"}
            ]
        },
        {
            "name": "Machine Coding",
            "category": "coding",
            "duration_minutes": 60,
            "description": "Build a working solution for a real-world problem demonstrating OOP skills",
            "skills": ["OOPS", "Design Patterns", "Clean Code", "Unit Testing"],
            "guidelines": [
                {"title": "Provide clear problem statement", "description": "Give a well-defined problem with sample input/output"},
                {"title": "Allow for code organization", "description": "Give time for proper class/module structure"},
                {"title": "Evaluate extensibility", "description": "Ask how they would extend the solution for new requirements"}
            ],
            "feedback_questions": [
                {"heading": "Requirements Clarification", "description": "Ability to identify and clarify ambiguous requirements"},
                {"heading": "Object Oriented Design", "description": "Use of OOP principles, design patterns, and code organization"},
                {"heading": "Adaptability", "description": "Response to changing requirements and ability to refactor"},
                {"heading": "Working Demo", "description": "Quality and completeness of the final working solution"}
            ]
        },
        {
            "name": "Systems Design",
            "category": "design",
            "duration_minutes": 45,
            "description": "Design a scalable distributed system architecture",
            "skills": ["Distributed Systems", "Scalability", "Database Design", "Caching", "Load Balancing"],
            "guidelines": [
                {"title": "Start with requirements and constraints", "description": "Have candidate identify functional and non-functional requirements"},
                {"title": "Focus on high-level design first", "description": "Ensure candidate creates a high-level architecture before diving into details"},
                {"title": "Discuss trade-offs", "description": "Ask candidate to explain trade-offs in their design decisions"}
            ],
            "feedback_questions": [
                {"heading": "Requirements Analysis", "description": "Ability to gather and clarify system requirements"},
                {"heading": "Architecture Quality", "description": "Overall system design and component organization"},
                {"heading": "Trade-off Analysis", "description": "Understanding of design trade-offs and justification of choices"},
                {"heading": "Scalability", "description": "Consideration for system growth and performance at scale"}
            ]
        },
        {
            "name": "Behavioural",
            "category": "behavioural",
            "duration_minutes": 30,
            "description": "Assess cultural fit, leadership qualities and soft skills",
            "skills": ["Leadership", "Communication", "Teamwork", "Conflict Resolution", "Ownership"],
            "guidelines": [
                {"title": "Use STAR format", "description": "Ask for Situation, Task, Action, Result in responses"},
                {"title": "Probe for specifics", "description": "Ask follow-up questions to get concrete examples"},
                {"title": "Assess culture fit", "description": "Evaluate alignment with company values and team dynamics"}
            ],
            "feedback_questions": [
                {"heading": "Leadership", "description": "Demonstrated leadership qualities and initiative"},
                {"heading": "Conflict Resolution", "description": "Approach to handling disagreements and difficult situations"},
                {"heading": "Ownership", "description": "Track record of taking responsibility and driving results"},
                {"heading": "Communication", "description": "Clarity and effectiveness in verbal communication"}
            ]
        }
    ]
}
