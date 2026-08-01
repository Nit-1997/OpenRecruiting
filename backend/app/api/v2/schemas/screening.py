"""Request/response schemas for the per-round screening agent config.

These are the API-layer Pydantic models (distinct from the intake-core
`ScreeningQuestion` dataclass, which is the voice-agent session-snapshot model).
"""

from pydantic import BaseModel, Field


class ScreeningQuestion(BaseModel):
    id: str | None = None
    order_index: int = 0
    title: str
    prompt: str
    probe: str | None = None
    signal: str | None = None
    dimension: str | None = None
    duration_minutes: int | None = 5


class ScreeningConfig(BaseModel):
    round_id: str
    enabled: bool = False
    voice: str = "aura-luna-en"
    follow_up_style: str = "adaptive_probes"
    est_duration_minutes: int | None = None
    validity_days: int = 7
    deploy_scope: str = "manual"
    questions: list[ScreeningQuestion] = []


class GenerateScreeningRequest(BaseModel):
    preferences: str | None = None


class ScreeningSuggestionResponse(BaseModel):
    """Proactive "add a screen?" nudge driven by recurring Cortex gaps.

    should_suggest=False is the always-safe default (cold start, no pattern, or a
    screen already enabled); reason/target_round_id are only meaningful when True.
    """

    should_suggest: bool = False
    reason: str = ""
    target_round_id: str | None = None


# --- Persona (config-time interviewer style) ------------------------------------


class PersonaDimensionModel(BaseModel):
    key: str
    value: str
    confidence: float = 0.0
    source: str = "generic"


class PersonaResponse(BaseModel):
    persona_id: str | None = None
    dimensions: list[PersonaDimensionModel] = []
    composed_text: str = ""


class SavePersonaRequest(BaseModel):
    dimensions: list[PersonaDimensionModel]


# --- Persona library (saved/reusable org personas) ------------------------------


class PersonaLibraryItem(BaseModel):
    """An org persona as returned by the library list/CRUD routes."""

    id: str
    name: str | None = None
    dimensions: list[PersonaDimensionModel] = []
    composed_text: str = ""
    is_template: bool = False
    requisition_id: str | None = None
    derived_at: str | None = None


class CreatePersonaRequest(BaseModel):
    name: str | None = None
    dimensions: list[PersonaDimensionModel] = []
    is_template: bool = False


class UpdatePersonaRequest(BaseModel):
    name: str | None = None
    dimensions: list[PersonaDimensionModel] | None = None
    is_template: bool | None = None


class SelectPersonaRequest(BaseModel):
    persona_id: str


class InviteRequest(BaseModel):
    emails: list[str] | None = None
    scope: str | None = None  # 'all_resume_passed'


# --- Public (no-login) candidate screening portal -------------------------------


class ScreeningContextResponse(BaseModel):
    """Pre-auth context for the candidate. Deliberately leaks NO OTP or ids."""

    role_title: str | None = None
    round_name: str | None = None
    email_hint: str | None = None
    has_active_session: bool = False


class ScreeningSendOTPResponse(BaseModel):
    success: bool
    message: str
    email_hint: str | None = None
    retry_after_seconds: int | None = None


class ScreeningVerifyOTPRequest(BaseModel):
    otp: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class ScreeningVerifyOTPResponse(BaseModel):
    success: bool
    session_token: str | None = None
    error: str | None = None
    locked_until: str | None = None
    attempts_remaining: int | None = None


class ScreeningSessionResponse(BaseModel):
    valid: bool = True
    role_title: str | None = None
    round_name: str | None = None
    candidate_email: str | None = None


class ScreeningStartVoiceRequest(BaseModel):
    redo: bool = False


class ScreeningStartVoiceResponse(BaseModel):
    voice_session_token: str
