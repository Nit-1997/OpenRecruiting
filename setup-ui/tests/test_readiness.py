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
    "ANTHROPIC_API_KEY": "k",
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
