"""Warm-container reuse test per CLAUDE.md mandatory rules.

Two handler invocations in the same Python process must succeed. Catches the
'Event loop is closed' bug that bit v1 in May 2026.

NOTE: The handler is a sync function that creates its own event loop internally.
This test must be sync (not async) so it runs outside any pytest-asyncio loop.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def _make_session_context():
    return {
        "session_id": "s1", "requisition_id": "r1", "organization_id": "o1",
        "role_title": "x", "experience_min_years": 0, "experience_max_years": 2,
        "role_location": "x", "intake_summary_struct": {}, "turns": [],
        "modalities_used": [], "duration_min": 0, "questions_version": "v1",
        "questions_snapshot": [],
    }


def test_mark_session_failed_rolls_back_status_to_ready():
    """mark_session_failed must set status='ready' so the user can retry submit."""
    with patch("src.clients.supabase.get_async_http_client") as mock_get_client, \
         patch("src.clients.supabase.get_settings") as mock_get_settings:
        mock_settings = MagicMock()
        mock_settings.supabase_url = "https://fake.supabase.co"
        mock_settings.supabase_service_role_key = "fake-key"
        mock_get_settings.return_value = mock_settings

        mock_http = AsyncMock()
        mock_get_client.return_value = mock_http

        from src.clients.supabase import SupabaseClient
        client = SupabaseClient()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(client.mark_session_failed("sess-xyz", "LLM 500"))
        loop.close()

        mock_http.patch.assert_called_once()
        call_kwargs = mock_http.patch.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["status"] == "ready", "status must roll back to 'ready' so user can retry"
        assert payload["process_status"] == "failed"
        assert "LLM 500" in payload["process_error"]


def test_handler_failure_calls_mark_session_failed():
    """When pipeline.run() raises, handler calls mark_session_failed with the error."""
    with patch("production.handler.SupabaseClient") as MockSB, \
         patch("production.handler.AnthropicClient") as MockAnt, \
         patch("production.handler.IntakePipelineV2") as MockPipe, \
         patch("production.handler.close_async_http_client", new_callable=AsyncMock):
        sb = MockSB.return_value
        sb.get_session_context = AsyncMock(return_value=_make_session_context())
        sb.mark_session_failed = AsyncMock()

        MockAnt.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        MockAnt.return_value.__aexit__ = AsyncMock(return_value=None)

        pipe = MockPipe.return_value
        pipe.run = AsyncMock(side_effect=RuntimeError("scorecard exploded"))

        from production.handler import handler
        result = handler({"session_id": "s-fail"}, MagicMock(aws_request_id="req-fail"))
        assert result["status"] == "failed"
        sb.mark_session_failed.assert_awaited_once()
        called_error = sb.mark_session_failed.call_args[0][1]
        assert "scorecard exploded" in called_error


def test_two_invocations_warm_succeed():
    with patch("production.handler.SupabaseClient") as MockSB, \
         patch("production.handler.AnthropicClient") as MockAnt, \
         patch("production.handler.IntakePipelineV2") as MockPipe, \
         patch("production.handler.close_async_http_client", new_callable=AsyncMock) as mock_close:
        sb = MockSB.return_value
        sb.get_session_context = AsyncMock(return_value=_make_session_context())
        sb.mark_session_failed = AsyncMock()

        MockAnt.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        MockAnt.return_value.__aexit__ = AsyncMock(return_value=None)

        pipe = MockPipe.return_value
        pipe.run = AsyncMock()

        from production.handler import handler
        r1 = handler({"session_id": "s1"}, MagicMock(aws_request_id="req-1"))
        assert r1["status"] == "completed"
        # Second invocation on same process must NOT crash with 'Event loop is closed'
        r2 = handler({"session_id": "s2"}, MagicMock(aws_request_id="req-2"))
        assert r2["status"] == "completed"
