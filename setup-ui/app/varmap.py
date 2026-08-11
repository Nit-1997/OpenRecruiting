"""Which setting belongs to which group, and which containers a change affects.

This is the restart-scoping mechanism. `affected_services` decides what bounces
when a value is saved, so a variable missing from here would be written to
`.env` and then applied to nothing, while the UI reported success — the
"looks applied, isn't" failure this codebase keeps producing.
`tests/test_varmap.py` fails if any key in `.env.example` is absent.

⚠️ `.env.example` IS NOT THE SOURCE OF TRUTH, and trusting it cost real coverage.
The first version of this map was built from that file and shipped without an
Email group, because `.env.example` declares no email variables — while
`backend/app/config.py` declares eight, including three API keys, all read by
`services/email/zoho_provider.py`. Eighty of its 101 settings are undocumented
there. So the completeness test now reads the Settings class itself, and every
field must be either mapped above or listed in UNMANAGED with a reason. An
unexplained gap is how the Resend key stayed invisible until someone asked.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Services that read Supabase and therefore restart when it changes. Kept as a
# named constant because six groups would otherwise repeat it and drift.
_SUPABASE_CONSUMERS = [
    "backend",
    "recruiter-app",
    "landing",
    "admin-app",
    "cortex-backend",
    "voice-agent",
    "feedback-agent",
    "intake-agent",
    "intake-context-builder",
]

_FRONTENDS = ["recruiter-app", "landing", "admin-app", "voice-frontend"]

# Everything that reaches an LLM through the gateway.
_GATEWAY_CLIENTS = [
    "backend",
    "voice-agent",
    "feedback-agent",
    "intake-agent",
    "intake-context-builder",
]


@dataclass(frozen=True)
class Variable:
    name: str
    label: str
    help: str = ""
    secret: bool = False
    required: bool = False
    services: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Group:
    id: str
    title: str
    blurb: str
    variables: list[Variable]


GROUPS: list[Group] = [
    Group(
        id="database",
        title="Database",
        blurb=(
            "The only hard requirement. Create a free project at supabase.com, "
            "paste the three values, then apply the schema below."
        ),
        variables=[
            Variable("SUPABASE_URL", "Project URL", "https://<project>.supabase.co",
                     required=True, services=_SUPABASE_CONSUMERS),
            Variable("SUPABASE_SECRET_KEY", "Service role key",
                     "Server-side only. Never reaches a browser.",
                     secret=True, required=True, services=_SUPABASE_CONSUMERS),
            Variable("SUPABASE_JWT_SECRET", "JWT secret",
                     "Signs backend-issued tokens (screening links, OTP).",
                     secret=True, services=["backend"]),
            Variable("NEXT_PUBLIC_SUPABASE_URL", "Project URL (browser)",
                     "Same value as above; the browser needs its own copy.",
                     services=_FRONTENDS),
            Variable("NEXT_PUBLIC_SUPABASE_ANON_KEY", "Anon key (browser)",
                     "Publishable by design — safe in a browser.",
                     services=_FRONTENDS),
            Variable("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "Publishable key (browser)",
                     "Supabase's newer name for the anon key. Either works.",
                     services=_FRONTENDS),
        ],
    ),
    Group(
        id="ai",
        title="AI models",
        blurb=(
            "Provider keys live only in the gateway. No application container "
            "holds one, and every workload picks its model by alias."
        ),
        variables=[
            Variable("ANTHROPIC_API_KEY", "Anthropic API key",
                     "Read by the litellm proxy only.", secret=True, services=["litellm"]),
            Variable("OPENAI_API_KEY", "OpenAI API key",
                     "Optional. Also used for graph embeddings.",
                     secret=True, services=["litellm", "cortex-backend"]),
            Variable("LITELLM_MASTER_KEY", "Gateway master key",
                     "How the services authenticate to the proxy.",
                     secret=True, required=True, services=["litellm"] + _GATEWAY_CLIENTS),
            Variable("LLM_GATEWAY_URL", "Gateway URL",
                     "Defaults to http://litellm:4000 inside compose.",
                     services=_GATEWAY_CLIENTS),
            Variable("LLM_TIMEOUT_SECONDS", "Request timeout (s)", services=_GATEWAY_CLIENTS),
            Variable("LLM_FORCE_JSON_TOOLS", "Force emulated JSON tools",
                     "Leave unset unless debugging a non-tool-capable model.",
                     services=_GATEWAY_CLIENTS),
            Variable("OLLAMA_API_BASE", "Ollama base URL",
                     "For running a local model through the gateway.",
                     services=["litellm"]),
        ],
    ),
    Group(
        id="voice",
        title="Voice",
        blurb="Speech-to-text and text-to-speech for the realtime agents.",
        variables=[
            Variable("DEEPGRAM_API_KEY", "Deepgram API key",
                     "Unset means the voice agent starts but cannot transcribe.",
                     secret=True, services=["voice-agent", "backend"]),
        ],
    ),
    Group(
        id="meetings",
        title="Meeting capture",
        blurb=(
            "Recall.ai is cloud-only and calls you, so it needs a publicly "
            "reachable webhook URL — a tunnel when running locally."
        ),
        variables=[
            Variable("RECALL_API_KEY", "Recall API key", secret=True, services=["backend"]),
            Variable("RECALL_BOT_NAME", "Bot display name", services=["backend"]),
            Variable("RECALL_WEBHOOK_SECRET", "Webhook signing secret",
                     secret=True, services=["backend"]),
            Variable("WEBHOOK_BASE_URL", "Public webhook base URL",
                     "Your tunnel, e.g. https://abc.ngrok-free.app. Unset means "
                     "bots record but callbacks never arrive.",
                     services=["backend"]),
        ],
    ),
    Group(
        id="graph",
        title="Knowledge graph",
        blurb="Neo4j and the cortex services behind it.",
        variables=[
            Variable("NEO4J_AUTH", "Neo4j auth (user/password)",
                     secret=True, services=["neo4j"]),
            Variable("NEO4J_URI", "Neo4j URI", services=["cortex-backend", "cortex-mcp"]),
            Variable("NEO4J_USERNAME", "Neo4j username",
                     services=["cortex-backend", "cortex-mcp"]),
            Variable("NEO4J_PASSWORD", "Neo4j password",
                     secret=True, services=["cortex-backend", "cortex-mcp"]),
            Variable("CORTEX_BACKEND_INTERNAL_URL", "Cortex backend URL",
                     services=["backend", "cortex-mcp"]),
            Variable("CORTEX_INTERNAL_SECRET", "Cortex internal secret",
                     secret=True, services=["backend", "cortex-backend", "cortex-mcp"]),
            Variable("CORTEX_MCP_URL", "Cortex MCP URL", services=["backend"]),
            Variable("CORTEX_TOKEN_URL", "Cortex token URL",
                     services=["backend", "intake-context-builder"]),
        ],
    ),
    Group(
        id="connectors",
        title="Connectors",
        blurb=(
            "The MCP server an assistant connects to. Unset signing key means "
            "MCP discovery returns 503."
        ),
        variables=[
            Variable("MCP_JWT_KEY_ID", "MCP key id", services=["cortex-mcp", "backend"]),
            Variable("MCP_JWT_PRIVATE_KEY_PEM", "MCP signing key (PEM)",
                     secret=True, services=["cortex-mcp", "backend"]),
            Variable("OIDC_ISSUER", "OIDC issuer", services=["backend", "cortex-mcp"]),
        ],
    ),
    Group(
        id="urls",
        title="App URLs",
        blurb=(
            "Where each app lives. Browser-facing values now apply on a restart "
            "— no image rebuild needed."
        ),
        variables=[
            Variable("APP_URL", "Backend-facing app URL", services=["backend"]),
            Variable("CORS_ORIGINS", "Allowed CORS origins", services=["backend"]),
            Variable("NEXT_PUBLIC_APP_URL", "Recruiter app URL", services=_FRONTENDS),
            Variable("NEXT_PUBLIC_API_URL", "Backend URL (browser)", services=_FRONTENDS),
            Variable("NEXT_PUBLIC_API_V2_URL", "Backend v2 URL (browser)", services=_FRONTENDS),
            Variable("NEXT_PUBLIC_LANDING_URL", "Landing URL", services=_FRONTENDS),
            Variable("NEXT_PUBLIC_COOKIE_DOMAIN", "Shared cookie domain",
                     "Blank for localhost. Set for cross-subdomain SSO.",
                     services=_FRONTENDS),
            Variable("NEXT_PUBLIC_ASSESSMENT_UI_URL", "Assessment UI URL", services=_FRONTENDS),
        ],
    ),
    Group(
        id="email",
        title="Email",
        blurb=(
            "Outbound mail: interview invitations, feedback links, password "
            "resets. Two providers are implemented — Zoho (ZeptoMail) and "
            "Resend. Unset means no mail is sent."
        ),
        variables=[
            Variable("EMAIL_PROVIDER", "Provider",
                     "zoho or resend. SendGrid and Postmark exist in the enum but "
                     "raise NotImplementedError at send time, so they are not "
                     "offered here — a field that looks configured and fails on "
                     "the first send is worse than no field.",
                     services=["backend"]),
            Variable("EMAIL_FROM_ADDRESS", "From address", services=["backend"]),
            Variable("EMAIL_FROM_NAME", "From name", services=["backend"]),
            Variable("ZEPTOMAIL_API_TOKEN", "ZeptoMail API token",
                     "Required when the provider is zoho.", secret=True, services=["backend"]),
            Variable("ZEPTOMAIL_BASE_URL", "ZeptoMail base URL", services=["backend"]),
            Variable("RESEND_API_KEY", "Resend API key",
                     "Required when the provider is resend.", secret=True, services=["backend"]),
        ],
    ),
    Group(
        id="integrations",
        title="Integrations",
        blurb=(
            "ATS sync and the worker callback secret. No cloud account is "
            "needed for either — the workers run as containers alongside "
            "everything else."
        ),
        variables=[
            Variable("KNIT_API_KEY", "Knit API key",
                     "ATS integrations. Unset disables ATS sync.",
                     secret=True, services=["backend"]),
            Variable("ATS_INTEGRATIONS_ENABLED", "Enable ATS sync",
                     "On by default; the Knit key above is what actually decides "
                     "whether sync can run.",
                     services=["backend"]),
            Variable("LAMBDA_CALLBACK_SECRET", "Worker callback secret",
                     "Shared secret background workers present when reporting "
                     "results. Despite the name this is NOT Lambda-only — the "
                     "backend rejects every worker callback when it is unset, "
                     "including on the default http path, so feedback results "
                     "never come back.",
                     secret=True, services=["backend"]),
        ],
    ),
    Group(
        id="advanced",
        title="Advanced",
        blurb="Internal wiring. Defaults are correct for compose.",
        variables=[
            Variable("INTERNAL_API_SECRET", "Internal API secret",
                     secret=True, services=["backend", "voice-agent"]),
            Variable("JOB_INVOKER", "Job invoker mode", services=["backend"]),
            Variable("SIGNUP_INVITE_ONLY", "Invite-only signup", services=["backend", "landing"]),
            Variable("FEEDBACK_WORKER_URL", "Feedback worker URL", services=["backend"]),
            Variable("INTAKE_WORKER_URL", "Intake worker URL", services=["backend"]),
            Variable("CONTEXT_BUILDER_WORKER_URL", "Context builder URL", services=["backend"]),
        ],
    ),
]

# Backend settings this UI deliberately does NOT surface. Every entry needs a
# reason, because the alternative — an unexplained gap — is how eight email
# settings including three API keys stayed invisible until someone asked why
# there was no Resend field. `tests/test_varmap.py` fails on any backend setting
# that is neither mapped above nor listed here.
UNMANAGED: dict[str, str] = {
    # Not implemented: the provider factory raises NotImplementedError for both,
    # so a field would look configured and fail on the first send.
    "SENDGRID_API_KEY": "provider not implemented",
    "POSTMARK_SERVER_TOKEN": "provider not implemented",
    # SaaS-only billing. Self-hosted instances get the built-in free tier.
    "DODO_PAYMENTS_API_KEY": "hosted billing only",
    "DODO_WEBHOOK_SECRET": "hosted billing only",
    "DODO_ENVIRONMENT": "hosted billing only",
    # Per-workload model ALIASES. Managed in the Models per task section, which
    # edits litellm-config.yaml — the layer that decides what an alias serves.
    **{
        name: "set in Models per task"
        for name in (
            "LLM_MODEL", "LLM_TEMPERATURE", "LLM_MAX_TOKENS",
            "ASSISTANT_INTENT_MODEL", "CANDIDATE_DETECT_MODEL", "DEBRIEF_CHAT_MODEL",
            "END_STATE_MODEL", "INTAKE_JD_MODEL", "INTAKE_TEXT_MODEL",
            "PERSONA_REDUCE_MODEL", "RECALL_TRANSCRIPT_MODEL", "RESUME_EXTRACTION_MODEL",
            "SCREENING_ASSESSOR_MODEL", "SCREENING_GENERATOR_MODEL",
            "DEBRIEF_CHAT_MAX_ITERS", "DEBRIEF_CHAT_MAX_TOKENS",
        )
    },
    # AWS. boto3 IS installed and s3_service.py IS real, so this is not dead
    # code — but it has exactly two callers: the admin blog CMS image upload and
    # ATS resume enrichment. Neither is part of a self-hosted install, and
    # JOB_INVOKER defaults to "http", which posts to the local worker containers
    # rather than Lambda. Surfacing AWS credentials in a setup UI implies an AWS
    # account is required for setup. It is not.
    **{
        name: "only the admin blog CMS and ATS resume enrichment; no AWS needed to self-host"
        for name in (
            "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION",
            "S3_RESUME_BUCKET", "S3_BLOG_BUCKET",
        )
    },
    # The legacy boto3 job path, reachable only with JOB_INVOKER=lambda.
    **{
        name: "legacy Lambda path; JOB_INVOKER defaults to http"
        for name in (
            "FEEDBACK_LAMBDA_ARN", "INTAKE_LAMBDA_ARN", "INTAKE_LAMBDA_ARN_V2",
            "INTAKE_CONTEXT_BUILDER_LAMBDA_ARN",
        )
    },
    # Tuning knobs with correct defaults. Surfacing 40 of these would bury the
    # six settings that actually block a first run.
    **{
        name: "tuning knob, default is correct"
        for name in (
            "ATS_ENRICHMENT_BATCH", "ATS_ENRICHMENT_INTERVAL_S", "ATS_ENRICHMENT_MAX_RETRIES",
            "ATS_INTERVIEW_RECONCILE_BATCH", "ATS_INTERVIEW_RECONCILE_INTERVAL_S",
            "ATS_RESUME_MAX_BYTES", "ATS_SYNC_DRAIN_BATCH", "ATS_SYNC_DRAIN_INTERVAL_S",
            "ATS_SYNC_MAX_RETRIES", "KNIT_API_BASE_URL",
            "CANDIDATE_DETECT_CHAR_THRESHOLD", "CANDIDATE_DETECT_CONFIDENCE_THRESHOLD",
            "CANDIDATE_DETECT_ENABLED", "CANDIDATE_DETECT_MIN_PARTICIPANTS",
            "END_STATE_CONFIDENCE_THRESHOLD", "END_STATE_DETECT_ENABLED",
            "END_STATE_GRACE_SECONDS",
            "RECALL_BASE_URL", "RECALL_BOT_EXIT_TIMEOUT", "RECALL_BOT_NOONE_JOINED_TIMEOUT",
            "RECALL_BOT_SILENCE_TIMEOUT", "RECALL_REALTIME_WEBHOOK_PATH",
            "RECALL_TRANSCRIPT_LANGUAGE", "RECALL_TRANSCRIPT_PROVIDER",
            "RECALL_TRANSCRIPT_SEPARATE_STREAMS", "RECALL_TRANSCRIPT_WORD_BOOST",
            "DEBUG", "ENV", "LOG_LEVEL", "RUN_BACKGROUND_WORKERS",
            "MCP_ALLOWED_AUDIENCES", "MCP_CONSENT_URL", "MCP_JWT_ISSUER",
            "ASSESSMENT_UI_URL",
            "VOICE_ENABLED", "VOICE_TTS_VOICE", "VOICE_AGENT_URL",
            "VOICE_AGENT_V2_URL", "VOICE_AGENT_V2_DRAIN_TIMEOUT_S",
            "VOICE_DEEPGRAM_API_KEY",
            "INTAKE_TRANSCRIPT_WORKER_URL",
        )
    },
}

_BY_NAME: dict[str, Variable] = {
    var.name: var for group in GROUPS for var in group.variables
}


def all_variables() -> set[str]:
    return set(_BY_NAME)


def is_secret(name: str) -> bool:
    var = _BY_NAME.get(name)
    return bool(var and var.secret)


def affected_services(names: list[str]) -> list[str]:
    """Containers that must restart for these variables to take effect.

    An unknown name contributes nothing rather than everything: failing closed
    here means a typo causes a no-op the user can see, not a full-stack bounce
    that drops live voice calls.
    """
    services: set[str] = set()
    for name in names:
        var = _BY_NAME.get(name)
        if var:
            services.update(var.services)
    return sorted(services)
