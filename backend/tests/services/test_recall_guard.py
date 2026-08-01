"""Recall.ai is optional; an unconfigured deployment must degrade, not crash.

These pin the two states a self-hoster can be in:
  - no API key at all            -> meeting capture is off
  - API key but no public URL    -> bots can be scheduled, but Recall cannot
                                    deliver the recording-complete callback
"""

from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.services.recall_service import RecallService, RecallServiceError

_REQUIRED = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_SECRET_KEY": "secret",
    "SUPABASE_JWT_SECRET": "jwt",
}


def _settings(**kw) -> Settings:
    return Settings(**{**_REQUIRED, **kw})


def test_recall_disabled_without_api_key():
    assert _settings(RECALL_API_KEY="").recall_enabled is False


def test_recall_enabled_with_api_key():
    assert _settings(RECALL_API_KEY="rc_test").recall_enabled is True


def test_webhooks_not_reachable_without_public_url():
    """The common local-dev state: a key is set, but nothing public to call back
    to. Capture is 'enabled' while callbacks are not reachable."""
    s = _settings(RECALL_API_KEY="rc_test", WEBHOOK_BASE_URL="")
    assert s.recall_enabled is True
    assert s.recall_webhooks_reachable is False


def test_webhooks_reachable_with_tunnel_url():
    s = _settings(RECALL_API_KEY="rc_test", WEBHOOK_BASE_URL="https://abc.ngrok-free.app")
    assert s.recall_webhooks_reachable is True


def test_no_public_url_alone_does_not_enable_recall():
    s = _settings(RECALL_API_KEY="", WEBHOOK_BASE_URL="https://abc.ngrok-free.app")
    assert s.recall_enabled is False
    assert s.recall_webhooks_reachable is False


@pytest.mark.asyncio
async def test_scheduling_a_bot_without_a_key_raises_a_clear_error():
    """The unconfigured path must surface a named error the API layer can map,
    not an AttributeError or an outbound call with an empty Authorization."""
    service = RecallService()
    service.api_key = ""

    with pytest.raises(RecallServiceError) as exc:
        await service.schedule_bot(
            meeting_url="https://meet.example.com/abc-defg-hij",
            scheduled_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            candidate_name="Dana Okafor",
            candidate_round_id="cr-1",
        )
    assert "RECALL_API_KEY" in str(exc.value)
