"""readiness.evaluate() is a pure function, so every branch is reachable from a
plain dict. These tests exist mostly to pin the promises the panel makes:
`live` must mean nothing is missing, `partial` must mean "looks configured and
is not", and Google sign-in must never be claimed as working.
"""

import pytest

from app.readiness import DORMANT, LIVE, PARTIAL, UNKNOWN, evaluate


CORE = {
    "SUPABASE_URL": "https://x.supabase.co",
    "SUPABASE_SECRET_KEY": "k",
    "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY": "k",
    "SUPABASE_JWT_SECRET": "k",
    "LITELLM_MASTER_KEY": "k",
}

FEATURE_VARS = {
    "meetings": ["RECALL_API_KEY", "RECALL_WEBHOOK_SECRET", "WEBHOOK_BASE_URL", "CLOUDFLARE_TOKEN"],
    "voice": ["DEEPGRAM_API_KEY"],
    "graph": ["NEO4J_PASSWORD", "CORTEX_INTERNAL_SECRET", "OPENAI_API_KEY"],
    "mcp": ["MCP_JWT_KEY_ID", "MCP_JWT_PRIVATE_KEY_PEM", "WEBHOOK_BASE_URL"],
    "ats": ["KNIT_API_KEY"],
    "callbacks": ["LAMBDA_CALLBACK_SECRET"],
}


def _by_id(values):
    return {f.id: f for f in evaluate(values)}


# ── the three states, per feature ───────────────────────────────────────────

@pytest.mark.parametrize("fid,names", FEATURE_VARS.items())
def test_all_set_is_live(fid, names):
    assert _by_id({n: "v" for n in names})[fid].state == LIVE


@pytest.mark.parametrize("fid,names", FEATURE_VARS.items())
def test_none_set_is_dormant(fid, names):
    f = _by_id({})[fid]
    assert f.state == DORMANT
    assert sorted(f.missing) == sorted(names)


@pytest.mark.parametrize(
    "fid,names",
    [(k, v) for k, v in FEATURE_VARS.items() if len(v) > 1],
)
def test_some_set_is_partial(fid, names):
    """The state worth surfacing loudest: it looks configured and is not."""
    f = _by_id({names[0]: "v"})[fid]
    assert f.state == PARTIAL
    assert names[0] not in f.missing
    assert names[1] in f.missing


def test_core_live_only_when_every_required_key_is_set():
    assert _by_id(CORE)["core"].state == LIVE
    for name in CORE:
        partial = dict(CORE)
        del partial[name]
        assert _by_id(partial)["core"].state == PARTIAL, name


# ── blank is not set ────────────────────────────────────────────────────────

@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_values_do_not_count_as_set(blank):
    """.env keeps every key present with an empty value, so membership is never
    the right test."""
    assert _by_id({"KNIT_API_KEY": blank})["ats"].state == DORMANT


# ── dependencies ────────────────────────────────────────────────────────────

def test_bot_voice_is_not_live_without_browser_voice():
    """TURN is meaningless if the agent cannot transcribe in the first place."""
    turn = {"TURN_SERVER_URL": "t", "TURN_USERNAME": "u", "TURN_CREDENTIAL": "c"}
    assert _by_id(turn)["bot_voice"].state == PARTIAL
    assert _by_id({**turn, "DEEPGRAM_API_KEY": "k"})["bot_voice"].state == LIVE


# ── either TURN provider satisfies meeting-bot voice ────────────────────────

def test_cloudflare_turn_alone_is_enough():
    """Regression: checking only the static trio reported a working Cloudflare
    relay as unconfigured, because Cloudflare mints short-lived credentials from
    a server-side key and has no static username/password to check."""
    values = {"DEEPGRAM_API_KEY": "k",
              "CLOUDFLARE_TURN_TOKEN_ID": "id", "CLOUDFLARE_TURN_API_TOKEN": "tok"}
    f = _by_id(values)["bot_voice"]
    assert f.state == LIVE
    assert f.missing == []


def test_static_turn_alone_is_enough():
    values = {"DEEPGRAM_API_KEY": "k", "TURN_SERVER_URL": "turn:x:3478",
              "TURN_USERNAME": "u", "TURN_CREDENTIAL": "c"}
    assert _by_id(values)["bot_voice"].state == LIVE


def test_neither_turn_provider_reports_the_cloudflare_pair():
    """With nothing set, name one path rather than every variable of both."""
    f = _by_id({"DEEPGRAM_API_KEY": "k"})["bot_voice"]
    assert f.state == DORMANT
    assert "CLOUDFLARE_TURN_TOKEN_ID" in f.missing
    assert "TURN_SERVER_URL" not in f.missing


def test_half_a_cloudflare_pair_is_partial_not_dormant():
    values = {"DEEPGRAM_API_KEY": "k", "CLOUDFLARE_TURN_TOKEN_ID": "id"}
    f = _by_id(values)["bot_voice"]
    assert f.state == PARTIAL
    assert f.missing == ["CLOUDFLARE_TURN_API_TOKEN"]


# ── required vs optional ────────────────────────────────────────────────────

REQUIRED_IDS = {"core", "models", "meetings", "voice", "bot_voice", "email", "callbacks"}
OPTIONAL_IDS = {"graph", "mcp", "ats", "google_auth"}


def test_the_required_set_matches_the_spec():
    """Pins the docs/superpowers/specs/2026-08-12-setup-wiki-design.md list, so
    the wiki and the panel cannot drift apart. An unset REQUIRED feature must
    never render as merely 'off'."""
    features = {f.id: f for f in evaluate({})}
    assert {i for i, f in features.items() if f.required} == REQUIRED_IDS
    assert {i for i, f in features.items() if not f.required} == OPTIONAL_IDS


# ── the chosen provider, not a hardcoded one ────────────────────────────────
# Core used to require ANTHROPIC_API_KEY outright. That reported Core: live for
# a user who had pasted an OpenRouter key into the Anthropic box — non-empty, so
# it passed — while every call 401'd against api.anthropic.com.


def test_models_is_live_when_the_default_providers_own_key_is_set():
    assert _by_id({**CORE, "ANTHROPIC_API_KEY": "k"})["models"].state == LIVE


def test_models_is_not_live_when_the_default_providers_key_is_empty():
    f = _by_id(CORE)["models"]
    assert f.state == PARTIAL
    assert f.missing == ["ANTHROPIC_API_KEY"]


def test_a_key_belonging_to_another_provider_does_not_satisfy_the_default():
    """The exact failure this replaced: a key IS set, just not the one the
    selected provider will be handed."""
    f = _by_id({**CORE, "OPENROUTER_API_KEY": "sk-or-v1-real"})["models"]
    assert f.state != LIVE
    assert "ANTHROPIC_API_KEY" in f.missing


def test_core_no_longer_depends_on_one_hardcoded_provider():
    """A user running entirely on OpenRouter must be able to reach Core: live
    without ever setting an Anthropic key."""
    assert _by_id(CORE)["core"].state == LIVE


def test_models_follows_the_registry_rather_than_a_hardcoded_provider():
    from app.providers import ProviderEntry, Registry
    from app.readiness import evaluate as ev

    registry = Registry(
        default="openrouter",
        providers={"openrouter": ProviderEntry(preferred="z-ai/glm-5.2")},
    )
    features = {f.id: f for f in ev({**CORE, "OPENROUTER_API_KEY": "sk-or-v1-real"}, registry)}
    assert features["models"].state == LIVE

    features = {f.id: f for f in ev({**CORE, "ANTHROPIC_API_KEY": "k"}, registry)}
    assert features["models"].state == PARTIAL, (
        "an Anthropic key must not make an OpenRouter deployment look ready"
    )


# ── email picks its required key from the provider ──────────────────────────

def test_email_dormant_with_no_provider():
    assert _by_id({})["email"].state == DORMANT


@pytest.mark.parametrize("provider,key", [("resend", "RESEND_API_KEY"),
                                          ("zoho", "ZEPTOMAIL_API_TOKEN")])
def test_email_live_with_provider_and_its_key(provider, key):
    values = {"EMAIL_PROVIDER": provider, "EMAIL_FROM_ADDRESS": "a@b.c", key: "k"}
    assert _by_id(values)["email"].state == LIVE


def test_email_partial_when_provider_set_but_its_key_is_not():
    f = _by_id({"EMAIL_PROVIDER": "resend", "EMAIL_FROM_ADDRESS": "a@b.c"})["email"]
    assert f.state == PARTIAL
    assert "RESEND_API_KEY" in f.missing


def test_email_ignores_the_other_providers_key():
    """A Zoho token does not make a Resend deployment ready."""
    values = {"EMAIL_PROVIDER": "resend", "EMAIL_FROM_ADDRESS": "a@b.c",
              "ZEPTOMAIL_API_TOKEN": "k"}
    assert _by_id(values)["email"].state == PARTIAL


@pytest.mark.parametrize("provider", ["sendgrid", "postmark"])
def test_unimplemented_providers_are_flagged_not_accepted(provider):
    """Both exist in the backend enum and raise NotImplementedError at send
    time, so reporting them live would be the exact 'looks configured, isn't'
    failure this panel is meant to prevent."""
    f = _by_id({"EMAIL_PROVIDER": provider, "EMAIL_FROM_ADDRESS": "a@b.c"})["email"]
    assert f.state == PARTIAL
    assert "not implemented" in f.consequence


# ── the honesty constraint ──────────────────────────────────────────────────

@pytest.mark.parametrize("values", [
    {},
    CORE,
    {**CORE, "GOOGLE_CLIENT_ID": "x", "GOOGLE_CLIENT_SECRET": "y"},
])
def test_google_auth_is_always_unknown(values):
    """It lives in the Supabase dashboard. This module cannot see it, and must
    never render a tick it has not earned — not even if someone puts
    Google-looking variables in .env."""
    f = _by_id(values)["google_auth"]
    assert f.state == UNKNOWN
    assert f.doc


# ── shape ───────────────────────────────────────────────────────────────────

def test_every_feature_explains_what_breaks():
    for f in evaluate({}):
        assert f.consequence, f.id


def test_live_features_never_report_missing_variables():
    everything = {n: "v" for names in FEATURE_VARS.values() for n in names}
    for f in evaluate({**CORE, **everything}):
        if f.state == LIVE:
            assert f.missing == [], f.id


# ── which provider credentials count ────────────────────────────────────────
# _models used to look at registry.default's key_var and nothing else. Both
# holes below reported "AI models: live" over a stack that 401s at request time,
# which is the exact failure this whole panel was added to catch.

def _registry(default, providers_map, overrides=None):
    from app.providers import ProviderEntry, Registry

    return Registry(
        default=default,
        providers={k: ProviderEntry(preferred=v) for k, v in providers_map.items()},
        overrides=overrides or {},
    )


def _models_feature(values, registry):
    return next(f for f in evaluate(values, registry) if f.id == "models")


def test_an_ollama_default_with_no_base_url_is_not_live():
    """Ollama needs no key, so checking only key_var reported an Ollama default
    with no address as fully configured. It is reached AT an address; without one
    every call fails."""
    feature = _models_feature({}, _registry("ollama", {"ollama": "gemma4:latest"}))
    assert feature.state == PARTIAL
    assert feature.missing == ["OLLAMA_API_BASE"]


def test_a_pinned_provider_with_an_empty_key_is_not_live():
    """An override serves real traffic. A default with a good key plus a pin to a
    keyless provider reported live while that one workload 401'd on every call."""
    feature = _models_feature(
        {"ANTHROPIC_API_KEY": "sk-ant-real"},
        _registry(
            "anthropic",
            {"anthropic": "claude-sonnet-5", "openrouter": "z-ai/glm-5.2"},
            overrides={"voice-intake": {"provider": "openrouter", "model": "z-ai/glm-5.2"}},
        ),
    )
    assert feature.state == PARTIAL
    assert feature.missing == ["OPENROUTER_API_KEY"]
    assert "voice-intake" in feature.consequence


def test_a_pinned_provider_whose_key_is_set_stays_live():
    feature = _models_feature(
        {"ANTHROPIC_API_KEY": "sk-ant-real", "OPENROUTER_API_KEY": "sk-or-real"},
        _registry(
            "anthropic",
            {"anthropic": "claude-sonnet-5", "openrouter": "z-ai/glm-5.2"},
            overrides={"voice-intake": {"provider": "openrouter", "model": "z-ai/glm-5.2"}},
        ),
    )
    assert feature.state == LIVE
