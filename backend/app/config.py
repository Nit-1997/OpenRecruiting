from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import model_validator
from functools import lru_cache

from app.services.recall_webhook.constants import BOT_SPEAKER_NAMES


def _find_env_file() -> str:
    """Return the local .env-fastapi path if it exists, else "" (Docker case).

    Local dev: __file__ = .../backend/app/config.py, so parents[2] is
    the repo root and we point pydantic at deploy-config/backend-deploy/env/.env-fastapi.
    Docker: __file__ = /app/app/config.py — parents[2] doesn't exist and the
    file isn't in the image either, so we return "" and let docker-compose
    env_file injection populate os.environ.
    """
    parents = Path(__file__).resolve().parents
    if len(parents) >= 3:
        candidate = parents[2] / "deploy-config" / "backend-deploy" / "env" / ".env-fastapi"
        if candidate.exists():
            return str(candidate)
    return ""


class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_SECRET_KEY: str  # New format: sb_secret_...
    SUPABASE_JWT_SECRET: str
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001,http://localhost:3005"
    DEBUG: bool = False
    ASSESSMENT_UI_URL: str = ""
    # Recruiter app base URL: every link the backend builds for a browser --
    # invite redirects, feedback and screening portals, billing. (Was three
    # settings for the same host, one per app generation. RECRUITER_PORTAL_URL
    # was the last straggler; unlike this one it had no default, so leaving it
    # unset silently produced relative URLs like "/set-password" that Supabase
    # rejects as redirect targets.)
    APP_URL: str = "http://localhost:3005"

    # When True, only pre-provisioned invitees may complete signup. Off by
    # default: on a self-hosted instance the operator already controls who can
    # authenticate at all, through their own Supabase auth settings.
    SIGNUP_INVITE_ONLY: bool = False

    # Where background jobs run: "http" posts to the local worker containers,
    # "lambda" keeps the original boto3 AWS path. See services/jobs/invoker.py.
    JOB_INVOKER: str = "http"
    FEEDBACK_WORKER_URL: str = "http://feedback-agent:9001"
    INTAKE_WORKER_URL: str = "http://intake-agent:9002"
    CONTEXT_BUILDER_WORKER_URL: str = "http://intake-context-builder:9003"
    INTAKE_CONTEXT_BUILDER_LAMBDA_ARN: str = ""
    # Deliberately blank: the pasted-transcript intake worker is a staff-only
    # tool that is not shipped here, so this target fails loudly instead of
    # posting the wrong payload shape to the self-serve intake worker.
    INTAKE_TRANSCRIPT_WORKER_URL: str = ""

    ENV: str = "development"  # development, uat, production, test
    LOG_LEVEL: str = ""  # Optional override: DEBUG, INFO, WARNING, ERROR

    # Whether the app lifespan launches its background worker loops
    # (intake lock cleanup). Forced False under ENV=test
    # so the test suite's TestClient(app) does not start loops that fire
    # unmocked Supabase calls.
    RUN_BACKGROUND_WORKERS: bool = True

    # Recall.ai Configuration. Optional: with no API key, meeting capture is
    # disabled (see `recall_enabled`) and the rest of the stack runs normally.
    RECALL_API_KEY: str = ""
    RECALL_BASE_URL: str = "https://us-west-2.recall.ai/api/v1"
    RECALL_WEBHOOK_SECRET: str = ""
    # Must be present (lowercased) in BOT_SPEAKER_NAMES -- asserted below.
    RECALL_BOT_NAME: str = "Scout"
    RECALL_BOT_EXIT_TIMEOUT: int = 300  # seconds to wait after everyone leaves (default 5 min)
    RECALL_BOT_NOONE_JOINED_TIMEOUT: int = 1800  # seconds to wait if no one joins (default 30 min)
    RECALL_BOT_SILENCE_TIMEOUT: int = 1800  # seconds of silence before leaving (default 30 min)

    # Webhook configuration for real-time events
    WEBHOOK_BASE_URL: str = ""  # Base URL for webhooks (e.g., https://your-domain.com or ngrok URL)

    # Path appended to WEBHOOK_BASE_URL when v2 creates a Recall bot. The
    # bot calls back to this URL with realtime events (participant join/leave,
    # transcript.data, chat). v1 is decommissioned — the only live realtime
    # handler is v2's (`/api/v2/webhooks/recall/realtime`, webhooks.py:114).
    # A v1 default would silently 404 every bot's realtime stream.
    RECALL_REALTIME_WEBHOOK_PATH: str = "/api/v2/webhooks/recall/realtime"

    # Transcription provider configuration
    # Options: recallai, deepgram, assemblyai
    RECALL_TRANSCRIPT_PROVIDER: str = "deepgram"
    # Model options vary by provider:
    #   recallai: prioritize_accuracy, prioritize_low_latency
    #   deepgram: nova-2, nova-3, enhanced, base
    #   assemblyai: (uses default model, can specify word_boost)
    RECALL_TRANSCRIPT_MODEL: str = "nova-2"
    RECALL_TRANSCRIPT_LANGUAGE: str = "en"
    # Comma-separated list of words to boost (for assemblyai/deepgram)
    RECALL_TRANSCRIPT_WORD_BOOST: str = ""
    # Use separate audio streams for better speaker diarization
    RECALL_TRANSCRIPT_SEPARATE_STREAMS: bool = True

    # LLM Configuration (for feedback extraction)
    # Model examples:
    #   OpenAI: gpt-4, gpt-4-turbo, gpt-3.5-turbo
    #   Anthropic: claude-3-opus-20240229, claude-3-sonnet-20240229
    #   Google: gemini/gemini-pro, gemini/gemini-1.5-pro
    LLM_MODEL: str = "gpt-4"
    LLM_TEMPERATURE: float = 0.0
    LLM_MAX_TOKENS: int = 4096

    # API keys for LLM providers (set the one you're using)
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""

    # Deepgram API key for real-time transcription
    DEEPGRAM_API_KEY: str = ""

    # Real-time candidate detection
    CANDIDATE_DETECT_ENABLED: bool = True
    CANDIDATE_DETECT_CHAR_THRESHOLD: int = 200
    CANDIDATE_DETECT_MIN_PARTICIPANTS: int = 2
    CANDIDATE_DETECT_CONFIDENCE_THRESHOLD: float = 0.9
    CANDIDATE_DETECT_MODEL: str = "claude-3-5-haiku-latest"

    # Interview end-state detection (LLM-holistic, Sonnet)
    END_STATE_DETECT_ENABLED: bool = True
    END_STATE_MODEL: str = "claude-sonnet-4-6"
    END_STATE_CONFIDENCE_THRESHOLD: float = 0.7
    END_STATE_GRACE_SECONDS: int = 60

    # AWS Configuration (for Lambda invocation)
    AWS_REGION: str = "us-west-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    FEEDBACK_LAMBDA_ARN: str = "arn:aws:lambda:us-west-1:771834037235:function:feedback-agent-worker"
    # Two intake Lambdas, two flows — both intentional (do NOT merge):
    #   INTAKE_LAMBDA_ARN  -> intake-agent-worker: the STAFF tool that
    #     processes a pasted intake transcript (admin UI: requisitions/[id]/plan
    #     -> POST /api/v2/admin/intake-jobs -> IntakeJobService). Its source now
    #     lives in a retired legacy tree (lambda still deployed).
    #   INTAKE_LAMBDA_ARN_V2 -> intake-agent-v2-worker: the RECRUITER self-serve
    #     intake (voice/text session -> intake_submit_service). Source: workers/intake-agent.
    INTAKE_LAMBDA_ARN: str = "arn:aws:lambda:us-west-1:771834037235:function:intake-agent-worker"
    INTAKE_LAMBDA_ARN_V2: str | None = None  # arn:aws:lambda:us-west-1:771834037235:function:intake-agent-v2-worker

    # Email Provider Configuration
    EMAIL_PROVIDER: str = "zoho"  # zoho, resend, sendgrid, postmark
    EMAIL_FROM_ADDRESS: str = "noreply@example.com"
    EMAIL_FROM_NAME: str = "OpenRecruiting"

    # ZeptoMail (Zoho) Configuration
    ZEPTOMAIL_API_TOKEN: str = ""
    ZEPTOMAIL_BASE_URL: str = "https://api.zeptomail.com/v1.1"

    # Resend Configuration
    RESEND_API_KEY: str = ""

    # Future providers (placeholders)
    SENDGRID_API_KEY: str = ""
    POSTMARK_SERVER_TOKEN: str = ""

    # Voice Agent Configuration
    VOICE_ENABLED: bool = False
    VOICE_AGENT_URL: str = ""
    # v2 intake voice agent (port 8011). Uses host.docker.internal because voice-agent
    # runs with network_mode:host while backend-v2 is on the default bridge network —
    # localhost inside the backend container resolves to the backend's own loopback, not the host.
    # extra_hosts in docker-compose.yml maps host.docker.internal to the gateway on Linux too.
    VOICE_AGENT_V2_URL: str = "http://host.docker.internal:8011"
    VOICE_AGENT_V2_DRAIN_TIMEOUT_S: float = 10.0
    VOICE_DEEPGRAM_API_KEY: str = ""
    VOICE_ANTHROPIC_API_KEY: str = ""
    VOICE_ANTHROPIC_MODEL: str = "claude-sonnet-4-6"
    VOICE_TTS_VOICE: str = "aura-2-helena-en"

    # Intake JD extract pipeline (sanitize -> injection guardrail -> parse). Haiku.
    INTAKE_JD_MODEL: str = "claude-haiku-4-5-20251001"

    # Ask-Anything intent router (browse_roles | intake_call | out_of_scope). Sonnet.
    ASSISTANT_INTENT_MODEL: str = "claude-sonnet-4-6"

    # Screening agent question generator (title/prompt/probe/signal/dimension). Sonnet.
    SCREENING_GENERATOR_MODEL: str = "claude-sonnet-4-6"

    # Screening agent assessor: authors the interviewer-style assessment from the
    # interview transcript (becomes scorecard_transcript -> feedback Lambda). Sonnet.
    SCREENING_ASSESSOR_MODEL: str = "claude-sonnet-4-6"

    # Lambda callback secret for feedback completion notifications
    LAMBDA_CALLBACK_SECRET: str = ""

    # S3 Blog Image Storage
    S3_BLOG_BUCKET: str = ""

    # Internal API (agent-to-backend communication)
    INTERNAL_API_SECRET: str = ""

    # Dodo Payments
    DODO_PAYMENTS_API_KEY: str = ""
    DODO_WEBHOOK_SECRET: str = ""
    DODO_ENVIRONMENT: str = "test_mode"

    # Knit (unified ATS integrations). KNIT_API_KEY doubles as the webhook
    # HMAC secret per Knit's signing contract (X-Knit-Signature).
    KNIT_API_KEY: str = ""
    KNIT_API_BASE_URL: str = "https://api.getknit.dev/v1.0"
    ATS_INTEGRATIONS_ENABLED: bool = False
    # Sync-event drainer (phase 2): poll cadence, batch size, and the retry
    # budget after which an event parks (processed with error retained).
    ATS_SYNC_DRAIN_INTERVAL_S: int = 15
    ATS_SYNC_DRAIN_BATCH: int = 50
    ATS_SYNC_MAX_RETRIES: int = 5
    # Candidate profile enrichment (resume signal extraction). Throttled,
    # sequential — one resume in memory at a time. Default ~10/hr (360s × batch 1).
    ATS_ENRICHMENT_INTERVAL_S: int = 360
    ATS_ENRICHMENT_BATCH: int = 1
    ATS_ENRICHMENT_MAX_RETRIES: int = 5
    ATS_RESUME_MAX_BYTES: int = 10_485_760  # 10MB cap on a downloaded resume
    RESUME_EXTRACTION_MODEL: str = "claude-sonnet-4-6"
    S3_RESUME_BUCKET: str = ""  # empty → skip durable resume copy (keep extracted signal)
    # Interview reconcile fallback (spec 2026-06-14 §5 trigger 2). 15 min default.
    ATS_INTERVIEW_RECONCILE_INTERVAL_S: int = 900
    ATS_INTERVIEW_RECONCILE_BATCH: int = 100  # application links pulled per connection per tick

    # MCP OAuth 2.1 authorization server
    # The PEM-encoded RSA private key used to sign access tokens. Public key
    # is derived and exposed at /.well-known/jwks.json.
    MCP_JWT_PRIVATE_KEY_PEM: str = ""
    # Stable kid identifier — must change on key rotation.
    MCP_JWT_KEY_ID: str = "mcp-key-1"
    # Issuer claim and discovery base URL. In production this is "http://localhost:8004".
    MCP_JWT_ISSUER: str = "http://localhost:8004"
    # Comma-separated allowlist of audience values (resource servers) we will
    # mint tokens for. Each is also the value of the `aud` claim.
    MCP_ALLOWED_AUDIENCES: str = "cortex-mcp"
    # URL of the consent screen on the marketing site. We redirect
    # /api/v1/mcp/oauth/authorize there with all OAuth params preserved.
    # If unset, /authorize falls back to an inline HTML form (dev only).
    MCP_CONSENT_URL: str = ""
    # Base URL of the Cortex MCP resource server. The screening persona reader
    # mints a cortex:read token in-process and POSTs execute_query to {url}/mcp.
    # Defaults to the internal docker-compose service URL.
    CORTEX_MCP_URL: str = "http://cortex-mcp:8020"

    # Base URL of the Cortex BACKEND (not the MCP) — the debrief skill lives here
    # at POST /api/v1/debrief, guarded by X-Internal-Secret. CortexDebriefClient
    # POSTs {org_id, requisition_id, candidate_ids} and gets a full DebriefPacket.
    # Defaults to the internal docker-compose service URL.
    CORTEX_BACKEND_INTERNAL_URL: str = "http://cortex-backend:8010"
    # OUTBOUND shared secret for the debrief skill call. This is DISTINCT from
    # INTERNAL_API_SECRET (the INBOUND secret this backend validates on its own
    # internal endpoints). It MUST equal
    # cortex-backend's INTERNAL_SECRET, which cortex validates the
    # X-Internal-Secret header against — conflating the two 401s every /generate.
    CORTEX_INTERNAL_SECRET: str = ""

    # Debrief conversation agent (chat over a generated packet). Sonnet, consistent
    # with the assistant-route + intake runtime LLMs (the strict-Opus rule governs
    # the coding agent, not in-product runtimes). MAX_ITERS bounds the in-loop read-
    # tool cycle to prevent a runaway tool loop.
    DEBRIEF_CHAT_MODEL: str = "claude-sonnet-4-6"
    DEBRIEF_CHAT_MAX_ITERS: int = 4
    DEBRIEF_CHAT_MAX_TOKENS: int = 2048

    @property
    def recall_enabled(self) -> bool:
        """Whether meeting capture is configured.

        Recall is optional. Without an API key the bot-scheduling paths report
        "not configured" instead of attempting a call, and the rest of the
        platform is unaffected. The webhook route stays mounted either way --
        it is harmless when no bots exist, and leaving it up avoids a confusing
        404 for anyone mid-setup.
        """
        return bool(self.RECALL_API_KEY)

    @property
    def recall_webhooks_reachable(self) -> bool:
        """Whether Recall can actually deliver callbacks to this deployment.

        Recall is cloud-only, so it needs a publicly reachable URL. Without one
        the bots still record but the recording-complete callback never lands,
        which is the difference between "capture works" and "capture starts and
        nothing comes back".
        """
        return self.recall_enabled and bool(self.WEBHOOK_BASE_URL)

    @model_validator(mode="after")
    def _disable_background_workers_under_test(self) -> "Settings":
        if self.ENV == "test":
            self.RUN_BACKGROUND_WORKERS = False
        return self

    @model_validator(mode="after")
    def _assert_recall_bot_name_excluded_as_speaker(self) -> "Settings":
        # Invariant: the bot's own utterances (labeled RECALL_BOT_NAME in Recall
        # transcripts) must be excluded from interviewer-feedback detection,
        # which keys off the lowercased BOT_SPEAKER_NAMES set. If RECALL_BOT_NAME
        # drifts out of that set, the bot's own speech is counted as interviewer
        # feedback and auto-triggers the feedback Lambda on empty rounds — the
        # May-2026 round 1ecc51c1 incident. Fail loud at startup instead.
        lowered = {name.lower() for name in BOT_SPEAKER_NAMES}
        if self.RECALL_BOT_NAME.lower() not in lowered:
            raise ValueError(
                f"RECALL_BOT_NAME={self.RECALL_BOT_NAME!r} (lowercased "
                f"{self.RECALL_BOT_NAME.lower()!r}) is not in BOT_SPEAKER_NAMES "
                f"{sorted(lowered)!r}. Add it to BOT_SPEAKER_NAMES in "
                "app/services/recall_webhook/constants.py (AND the matching set in "
                "workers/feedback-agent/src/clients/supabase.py) or the "
                "bot's own utterances will be counted as interviewer feedback."
            )
        return self

    class Config:
        env_file = _find_env_file()
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
