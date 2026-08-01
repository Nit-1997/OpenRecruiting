"""BE-F4: config default hygiene + RECALL_BOT_NAME / BOT_SPEAKER_NAMES invariant.

These tests guard against two regressions:
  1. Stale frontend/issuer defaults drifting from reality (APP_URL,
     MCP_JWT_ISSUER, CORS_ORIGINS all referenced a dead :3004 / localhost:8000).
  2. The bot-speaker-exclusion invariant: RECALL_BOT_NAME lowercased MUST be in
     BOT_SPEAKER_NAMES, else the bot's own utterances get counted as
     interviewer feedback (the May-2026 round 1ecc51c1 incident).

Test env is supplied by tests/conftest.py (sets ENV=test and the required
secrets via os.environ), so Settings() constructs without real credentials.
"""

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.recall_webhook.constants import BOT_SPEAKER_NAMES


def test_app_url_default_is_3005(monkeypatch):
    """The recruiter app runs on :3005; the default must not be the dead :3004.

    tests/mcp/conftest.py sets APP_URL in os.environ at import time, so
    clear it to exercise the class default rather than a stray env override.
    """
    monkeypatch.delenv("APP_URL", raising=False)
    settings = Settings()
    assert settings.APP_URL == "http://localhost:3005"


def test_cors_default_has_no_dead_3004(monkeypatch):
    """CORS default list must point at :3005, not the retired :3004.

    conftest sets CORS_ORIGINS in os.environ, so clear it to exercise the
    class default rather than the test env override.
    """
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    settings = Settings()
    assert "3004" not in settings.CORS_ORIGINS
    assert "http://localhost:3005" in settings.CORS_ORIGINS


def test_mcp_jwt_issuer_default_is_prod_issuer(monkeypatch):
    """Default issuer must be the prod value localhost:8004, not localhost:8000.

    tests/mcp/conftest.py sets MCP_JWT_ISSUER in os.environ at import time, so
    clear it to exercise the class default rather than a stray env override.
    """
    monkeypatch.delenv("MCP_JWT_ISSUER", raising=False)
    settings = Settings()
    assert settings.MCP_JWT_ISSUER == "http://localhost:8004"


def test_default_recall_bot_name_is_in_speaker_set():
    """The shipped default RECALL_BOT_NAME must already be excluded as a speaker."""
    settings = Settings()
    assert settings.RECALL_BOT_NAME.lower() in {n.lower() for n in BOT_SPEAKER_NAMES}


def test_speaker_validator_raises_for_unlisted_bot_name():
    """If RECALL_BOT_NAME drifts out of BOT_SPEAKER_NAMES, Settings must fail loud."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(RECALL_BOT_NAME="Some Unlisted Bot Name")
    assert "BOT_SPEAKER_NAMES" in str(exc_info.value)


def test_speaker_validator_passes_for_listed_bot_name_case_insensitive():
    """A bot name that matches the set (any case) must construct fine."""
    settings = Settings(RECALL_BOT_NAME="SCOUT AI")
    assert settings.RECALL_BOT_NAME == "SCOUT AI"


def test_knit_settings_defaults():
    """Knit settings exist with safe defaults; conftest injects the test key + flag."""
    from app.config import get_settings

    settings = get_settings()
    assert settings.KNIT_API_KEY == "test-knit-key"
    assert settings.KNIT_API_BASE_URL == "https://api.getknit.dev/v1.0"
    assert settings.ATS_INTEGRATIONS_ENABLED is True
