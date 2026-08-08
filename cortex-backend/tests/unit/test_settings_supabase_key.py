"""Which env var supplies the Supabase key, and whether we say so out loud.

A stale `SUPABASE_SERVICE_ROLE_KEY` left in an operator's shell used to outrank
the canonical `SUPABASE_SECRET_KEY` and 401 every Supabase call with nothing in
the logs naming the culprit.
"""

import pytest
import structlog

from src.config.settings import get_settings

KEY_VARS = ("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY")


@pytest.fixture
def clean_settings(monkeypatch):
    """`get_settings` is `@lru_cache`'d; bust it either side of each case."""
    for var in KEY_VARS:
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def captured_logs():
    structlog.configure(processors=[structlog.testing.LogCapture()])
    cap = structlog.get_config()["processors"][0]
    yield cap.entries
    structlog.reset_defaults()


def test_secret_key_wins_over_service_role_key(clean_settings, monkeypatch):
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "canonical")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "stale-legacy")

    assert get_settings().supabase.service_role_key == "canonical"


def test_service_role_key_still_works_alone(clean_settings, monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "legacy-only")

    assert get_settings().supabase.service_role_key == "legacy-only"


def test_empty_secret_key_falls_through_to_service_role_key(clean_settings, monkeypatch):
    # docker-compose.yml passes these through as `NAME=${NAME}`, which injects ""
    # rather than omitting the var when the operator never exported it.
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "legacy-fallback")

    assert get_settings().supabase.service_role_key == "legacy-fallback"


def test_both_empty_leaves_key_unset(clean_settings, monkeypatch):
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")

    assert get_settings().supabase.service_role_key == ""


def test_logs_which_var_resolved(clean_settings, captured_logs, monkeypatch):
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "canonical")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "stale-legacy")

    get_settings()

    resolved = [e for e in captured_logs if e["event"] == "supabase_key_resolved"]
    assert len(resolved) == 1
    assert resolved[0]["env_var"] == "SUPABASE_SECRET_KEY"


def test_logs_never_carry_the_key_value(clean_settings, captured_logs, monkeypatch):
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_do_not_leak")

    get_settings()

    assert "sb_secret_do_not_leak" not in str(captured_logs)


def test_logs_a_warning_when_no_key_var_is_set(clean_settings, captured_logs):
    get_settings()

    assert any(e["event"] == "supabase_key_missing" for e in captured_logs)
