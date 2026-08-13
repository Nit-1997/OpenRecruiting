"""What actually works right now, and what have you not finished?

The setup page could already answer two questions — are the containers up
(`/api/health`) and is the schema applied (`/api/database`) — but neither is the
question a first-time operator has. Both can be green while meeting capture
silently drops every webhook.

That gap is not hypothetical. Several features fail in ways that do not look
like configuration problems:

  * LAMBDA_CALLBACK_SECRET unset — the backend rejects every worker callback, so
    feedback results never come back. Nothing reports it.
  * RECALL_WEBHOOK_SECRET unset — bots join the call and every callback is
    rejected, so nothing is ever captured.
  * TURN_* unset — browser voice works, meeting-bot voice cannot reach the agent
    through NAT.
  * EMAIL_PROVIDER unset — no interview invitations, feedback links or password
    resets are sent.

`evaluate()` is deliberately PURE: dict in, list out. No Docker, no network, no
file reads. That makes every branch unit-testable and means this panel cannot
be the thing that breaks the setup page.

HONESTY CONSTRAINT. Google sign-in is configured in the Supabase dashboard, not
in `.env`, and the service key cannot read auth provider settings. It is
therefore reported as `unknown` — never as a green tick this module has not
earned. Same discipline as `supabase_setup.py`: report what is measurable and
hand over exact steps for the rest. "Looks configured, isn't" is the failure
this codebase keeps producing.
"""

from __future__ import annotations

from dataclasses import dataclass, field


LIVE = "live"
PARTIAL = "partial"
DORMANT = "dormant"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Feature:
    id: str
    name: str
    state: str
    missing: list[str]
    consequence: str
    #: False only for the genuinely optional: Google OAuth, the knowledge graph,
    #: the MCP connector and ATS sync. Everything else is needed to run a real
    #: session, and reporting it as merely "off" understates a half-built
    #: instance.
    required: bool = True
    #: Where to go when this cannot be settled from `.env` alone.
    doc: str = ""


@dataclass(frozen=True)
class _Spec:
    id: str
    name: str
    requires: tuple[str, ...]
    consequence: str
    #: An equally valid alternative set. Satisfying EITHER makes the feature
    #: live — see the two TURN providers below.
    alt_requires: tuple[str, ...] = ()
    #: Features that are meaningless on their own. Meeting-bot voice needs a
    #: working browser voice stack before TURN is worth reporting on.
    depends_on: str = ""
    required: bool = True


#: Order matters — this is the order the panel renders in, most fundamental
#: first. `requires` lists only variables a human sets; values written by
#: another field (see derive.py) are represented by their source field.
_SPECS: tuple[_Spec, ...] = (
    _Spec(
        "core", "Core",
        ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY",
         "SUPABASE_JWT_SECRET", "ANTHROPIC_API_KEY", "LITELLM_MASTER_KEY"),
        "Sign-in, requisitions and intake do not work.",
    ),
    _Spec(
        "meetings", "Meeting capture",
        ("RECALL_API_KEY", "RECALL_WEBHOOK_SECRET", "WEBHOOK_BASE_URL", "CLOUDFLARE_TOKEN"),
        "No bot can join a call, or it joins and every callback is rejected so "
        "nothing is captured.",
    ),
    _Spec(
        "voice", "Browser voice",
        ("DEEPGRAM_API_KEY",),
        "The voice agent starts but cannot transcribe anything.",
    ),
    # Two TURN providers, either of which is complete on its own. Cloudflare
    # mints short-lived credentials from a server-side key, so it CANNOT be
    # expressed as a static url/username/credential triple — checking only the
    # static trio reported a working Cloudflare relay as unconfigured.
    _Spec(
        "bot_voice", "Meeting-bot voice",
        ("CLOUDFLARE_TURN_TOKEN_ID", "CLOUDFLARE_TURN_API_TOKEN"),
        "A Recall bot cannot reach the voice agent through NAT. Browser voice "
        "is unaffected.",
        alt_requires=("TURN_SERVER_URL", "TURN_USERNAME", "TURN_CREDENTIAL"),
        depends_on="voice",
    ),
    _Spec(
        "graph", "Knowledge graph",
        ("NEO4J_PASSWORD", "CORTEX_INTERNAL_SECRET", "OPENAI_API_KEY"),
        "No graph is built, so Cortex cannot answer questions about your data.",
        required=False,
    ),
    _Spec(
        "mcp", "MCP connector",
        ("MCP_JWT_KEY_ID", "MCP_JWT_PRIVATE_KEY_PEM", "WEBHOOK_BASE_URL"),
        "Connector discovery returns 503, so no assistant can attach.",
        required=False,
    ),
    _Spec(
        "ats", "ATS sync",
        ("KNIT_API_KEY",),
        "No ATS is synced.",
        required=False,
    ),
    _Spec(
        "callbacks", "Worker callbacks",
        ("LAMBDA_CALLBACK_SECRET",),
        "The backend rejects every background-worker callback, so feedback "
        "results never come back.",
    ),
)


#: Email is special-cased: which key is required depends on the provider chosen,
#: so a flat `requires` tuple cannot express it.
_EMAIL_PROVIDER_KEYS = {"resend": "RESEND_API_KEY", "zoho": "ZEPTOMAIL_API_TOKEN"}


def _set(values: dict[str, str], name: str) -> bool:
    """A variable counts as set only if it has a non-blank value. `.env` keeps
    every key present with an empty value, so `in` is never the right test."""
    return bool((values.get(name) or "").strip())


def _state(missing: list[str], total: int) -> str:
    if not missing:
        return LIVE
    return DORMANT if len(missing) == total else PARTIAL


def _email(values: dict[str, str]) -> Feature:
    consequence = (
        "No interview invitations, feedback links or password resets are sent."
    )
    provider = (values.get("EMAIL_PROVIDER") or "").strip().lower()

    if not provider:
        return Feature(
            "email", "Email", DORMANT,
            ["EMAIL_PROVIDER", "EMAIL_FROM_ADDRESS"], consequence,
        )

    if provider not in _EMAIL_PROVIDER_KEYS:
        # SendGrid and Postmark exist in the backend enum but raise
        # NotImplementedError at send time, so a configured-looking value here
        # would fail on the first send.
        return Feature(
            "email", "Email", PARTIAL, ["EMAIL_PROVIDER"],
            f"Provider {provider!r} is not implemented — sending raises at "
            "runtime. Use 'resend' or 'zoho'.",
        )

    missing = [n for n in ("EMAIL_FROM_ADDRESS", _EMAIL_PROVIDER_KEYS[provider])
               if not _set(values, n)]
    return Feature("email", "Email", _state(missing, 3), missing, consequence)


def evaluate(values: dict[str, str]) -> list[Feature]:
    """Map `.env` values to what is and is not working. Pure."""
    features: list[Feature] = []
    states: dict[str, str] = {}

    for spec in _SPECS:
        missing = [n for n in spec.requires if not _set(values, n)]
        state = _state(missing, len(spec.requires))

        if spec.alt_requires:
            alt_missing = [n for n in spec.alt_requires if not _set(values, n)]
            alt_state = _state(alt_missing, len(spec.alt_requires))
            # Whichever provider the operator actually started configuring is
            # the one to report on. Reporting both would list every variable of
            # the road not taken as "missing".
            if alt_state == LIVE or (state == DORMANT and alt_state == PARTIAL):
                missing, state = alt_missing, alt_state

        # A dependency that is not live makes this feature unreachable however
        # complete its own settings are.
        if spec.depends_on and states.get(spec.depends_on) != LIVE:
            state = PARTIAL if state == LIVE else state

        states[spec.id] = state
        features.append(Feature(
            spec.id, spec.name, state, missing, spec.consequence,
            required=spec.required,
        ))

    features.append(_email(values))

    # Not determinable from .env — see the module docstring.
    features.append(Feature(
        "google_auth", "Google sign-in", UNKNOWN, [],
        "Configured in the Supabase dashboard, not here, so this page cannot "
        "check it.",
        required=False,
        doc="docs/setup/google-auth.md",
    ))

    return features
