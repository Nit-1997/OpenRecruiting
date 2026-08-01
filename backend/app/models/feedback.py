from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class FeedbackAccessToken(BaseModel):
    id: str
    token: str
    candidate_round_id: str
    interviewer_email: str
    is_registered_user: Optional[bool] = None
    otp_code: Optional[str] = None
    otp_expires_at: Optional[str] = None
    otp_attempts: int = 0
    otp_locked_until: Optional[str] = None
    session_expires_at: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class FeedbackContextResponse(BaseModel):
    requires_otp: bool
    requires_platform_login: bool
    has_active_session: bool
    candidate_name: Optional[str] = None
    round_name: Optional[str] = None
    email_hint: Optional[str] = None


class SendOTPResponse(BaseModel):
    success: bool
    message: str
    email_hint: Optional[str] = None
    retry_after_seconds: Optional[int] = None


class VerifyOTPRequest(BaseModel):
    otp: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class VerifyOTPResponse(BaseModel):
    success: bool
    session_token: Optional[str] = None
    error: Optional[str] = None
    locked_until: Optional[str] = None
    attempts_remaining: Optional[int] = None


class FeedbackQuestion(BaseModel):
    question_number: int
    heading: str
    description: Optional[str] = None


class FeedbackSessionResponse(BaseModel):
    candidate_name: str
    candidate_email: str
    round_name: str
    round_type: str
    interview_date: Optional[str] = None
    has_transcript: bool
    has_scorecard: bool
    existing_transcript: Optional[str] = None
    has_existing_feedback: bool = False
    questions: Optional[List[FeedbackQuestion]] = None


class StartVoiceRequest(BaseModel):
    redo: bool = False


class StartVoiceResponse(BaseModel):
    voice_session_token: str


class VoiceCompleteRequest(BaseModel):
    candidate_round_id: str
    voice_session_token: str
    transcript: str = ""
    status: str = Field(..., pattern=r"^(completed|error)$")
    error_reason: Optional[str] = None


class VoiceCompleteResponse(BaseModel):
    success: bool
    processing_status: Optional[str] = None
    reason: Optional[str] = None


class QuestionSummary(BaseModel):
    question_number: int
    question_text: str
    description: Optional[str] = None
    summary: Optional[str] = None


class FeedbackReviewResponse(BaseModel):
    candidate_round_id: str
    candidate_name: str
    round_name: str
    interview_date: Optional[str] = None
    processing_status: str
    summary: Optional[str] = None
    rating: Optional[str] = None
    question_summaries: Optional[List[QuestionSummary]] = None
    can_edit: bool = True
    is_approved: bool = False
    approved_at: Optional[str] = None
    feedback_voice_session_status: Optional[str] = None
    feedback_voice_session_error: Optional[str] = None


class FeedbackEditRequest(BaseModel):
    summary: Optional[str] = None
    rating: Optional[str] = Field(None, pattern=r"^(strong_yes|yes|maybe|no|strong_no)$")
    question_summaries: Optional[Dict[str, str]] = None


class FeedbackEditResponse(BaseModel):
    success: bool
    message: str


class FeedbackApproveResponse(BaseModel):
    success: bool
    message: str
    approved_at: Optional[str] = None


class FeedbackReprocessRequest(BaseModel):
    updated_transcript: str = Field(..., min_length=10, max_length=50000)


class FeedbackReprocessResponse(BaseModel):
    success: bool
    message: str
    reprocessing: bool = False
    processing_status: Optional[str] = None
