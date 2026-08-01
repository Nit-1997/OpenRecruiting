"""BE-F0: background workers must NOT start under ENV=test.

The app lifespan unconditionally launched 4 background loops via
asyncio.create_task(...). Because the test suite drives the lifespan via
TestClient(app), every test fired unmocked Supabase HTTP calls from those
loops. This test pins the guard: under ENV=test the loop entrypoints are
never invoked when entering the lifespan.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.config import get_settings


def test_background_loops_not_scheduled_under_env_test():
    settings = get_settings()
    assert settings.ENV == "test", "conftest must set ENV=test before importing app"

    with patch("app.main.run_stale_lock_cleanup_loop") as cleanup_loop, \
         patch("app.main.run_slack_token_refresh_loop") as slack_loop, \
         patch("app.main.run_calendar_intelligence_loops") as cal_loop, \
         patch("app.main.run_deferred_backfill") as backfill_loop:
        with TestClient(app, raise_server_exceptions=False):
            pass

    cleanup_loop.assert_not_called()
    slack_loop.assert_not_called()
    cal_loop.assert_not_called()
    backfill_loop.assert_not_called()
