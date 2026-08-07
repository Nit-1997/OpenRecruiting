"""Defaults are a product decision, so they get a test.

Every one of these was found switched off on a fully-configured instance, and
each cost real debugging time before anyone suspected a default.

tests/conftest.py exports a test environment (ENV=test, ATS_INTEGRATIONS_ENABLED)
that would mask the shipped class defaults, so each case clears those names first.
"""
from app.config import Settings

_TEST_ENV_OVERRIDES = (
    "ENV",
    "VOICE_ENABLED",
    "ATS_INTEGRATIONS_ENABLED",
    "RUN_BACKGROUND_WORKERS",
    "SIGNUP_INVITE_ONLY",
    "DEBUG",
)


def _defaults(monkeypatch) -> Settings:
    for name in _TEST_ENV_OVERRIDES:
        monkeypatch.delenv(name, raising=False)
    return Settings(
        SUPABASE_URL="https://example.supabase.co",
        SUPABASE_SECRET_KEY="sb_secret_test",
        SUPABASE_JWT_SECRET="test-secret",
    )


def test_voice_is_on_by_default(monkeypatch):
    # Gates /start-voice on the feedback and screening portals. Voice ships as
    # two containers; DEEPGRAM_API_KEY and OPENAI_API_KEY already decide
    # whether it can actually work.
    assert _defaults(monkeypatch).VOICE_ENABLED is True


def test_ats_integrations_are_on_by_default(monkeypatch):
    # Credentials live per-organization in ats_connections, not in env, so
    # there is nothing to gate on. With no connection rows the loops idle.
    assert _defaults(monkeypatch).ATS_INTEGRATIONS_ENABLED is True


def test_background_workers_run_by_default(monkeypatch):
    # Was off because it dragged in Slack and calendar. With those deleted it
    # is just intake stale-lock cleanup, which is wanted.
    assert _defaults(monkeypatch).RUN_BACKGROUND_WORKERS is True


def test_signup_is_not_invite_gated_and_debug_is_off(monkeypatch):
    # These two are correctly False; asserted so a later sweep does not flip
    # them along with the rest.
    s = _defaults(monkeypatch)
    assert s.SIGNUP_INVITE_ONLY is False
    assert s.DEBUG is False


def test_deleted_features_have_no_settings_left():
    fields = set(Settings.model_fields)
    assert not [f for f in fields if f.startswith(("SLACK_", "GOOGLE_"))]
    assert "CALENDAR_INTELLIGENCE_ENABLED" not in fields
