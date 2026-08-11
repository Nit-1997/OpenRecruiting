"""Which setting belongs to which group, and which containers a change affects.

This is the restart-scoping mechanism. `affected_services` decides what bounces
when a value is saved, so a variable missing from here would be written to
`.env` and then applied to nothing, while the UI reported success — the
"looks applied, isn't" failure this codebase keeps producing.
`tests/test_varmap.py` fails if any key in `.env.example` is absent.

Deviation from the spec, recorded deliberately: the spec listed an "Email" group
(from the architecture doc's degradation table), but `.env.example` declares no
email variables at all. Rendering an empty section would be noise, so the group
is dropped and the eight URL/CORS settings get a group instead.
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
