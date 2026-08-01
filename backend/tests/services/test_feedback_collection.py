"""Characterization tests for recall_webhook.feedback_collection routing."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.recall_webhook import feedback_collection as fc


class _BG:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *a, **k):
        self.tasks.append((fn, a, k))


def _settings(voice=False):
    return SimpleNamespace(VOICE_ENABLED=voice)


@pytest.mark.asyncio
async def test_voice_path_activates_agent():
    bot = {"id": "db1", "candidate_round_id": "cr1", "voice_session_token": "vt"}
    recall = MagicMock()
    recall.send_chat_message = AsyncMock()
    recall.close = AsyncMock()
    with patch.object(fc, "get_settings", lambda: _settings(voice=True)), \
         patch.object(fc, "_update_bot", AsyncMock()) as upd, \
         patch.object(fc, "get_recall_service", return_value=recall):
        await fc.trigger_feedback_collection(bot, "rb1", "participant_leave", _BG())
    recall.send_chat_message.assert_awaited_once()
    recall.close.assert_awaited_once()
    assert upd.await_args.args[1]["feedback_status"] == "voice_active"


@pytest.mark.asyncio
async def test_voice_path_missing_round_falls_back():
    bot = {"id": "db1", "candidate_round_id": None, "voice_session_token": "vt"}
    bg = _BG()
    with patch.object(fc, "get_settings", lambda: _settings(voice=True)), \
         patch.object(fc, "_update_bot", AsyncMock()) as upd:
        await fc.trigger_feedback_collection(bot, "rb1", "participant_leave", bg)
    # fallback path sets the missing-round error code + enqueues a prompt
    assert upd.await_args.args[1]["error_code"] == "missing_candidate_round"
    assert len(bg.tasks) == 1


@pytest.mark.asyncio
async def test_voice_activation_chat_failure_still_closes():
    bot = {"id": "db1", "candidate_round_id": "cr1", "voice_session_token": "vt"}
    recall = MagicMock()
    recall.send_chat_message = AsyncMock(side_effect=RuntimeError("recall down"))
    recall.close = AsyncMock()
    with patch.object(fc, "get_settings", lambda: _settings(voice=True)), \
         patch.object(fc, "_update_bot", AsyncMock()), \
         patch.object(fc, "get_recall_service", return_value=recall):
        await fc.trigger_feedback_collection(bot, "rb1", "participant_leave", _BG())
    recall.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_command_path_enqueues_scorecard():
    bot = {"id": "db1", "candidate_round_id": "cr1"}
    bg = _BG()
    with patch.object(fc, "get_settings", lambda: _settings(voice=False)), \
         patch.object(fc, "_update_bot", AsyncMock()) as upd:
        await fc.trigger_feedback_collection(bot, "rb1", "chat_command", bg)
    assert upd.await_args.args[1]["feedback_status"] == "collecting"
    assert len(bg.tasks) == 1


@pytest.mark.asyncio
async def test_chat_command_missing_round_falls_back():
    bot = {"id": "db1", "candidate_round_id": None}
    bg = _BG()
    with patch.object(fc, "get_settings", lambda: _settings(voice=False)), \
         patch.object(fc, "_update_bot", AsyncMock()) as upd:
        await fc.trigger_feedback_collection(bot, "rb1", "chat_command", bg)
    assert upd.await_args.args[1]["error_code"] == "missing_candidate_round"


@pytest.mark.asyncio
async def test_default_path_prompts_interviewer_and_sets_clock():
    bot = {"id": "db1", "candidate_round_id": "cr1", "feedback_started_at": None}
    bg = _BG()
    with patch.object(fc, "get_settings", lambda: _settings(voice=False)), \
         patch.object(fc, "_update_bot", AsyncMock()) as upd:
        await fc.trigger_feedback_collection(bot, "rb1", "participant_leave", bg)
    payload = upd.await_args.args[1]
    assert payload["feedback_status"] == "waiting_for_yes"
    assert "feedback_started_at" in payload  # clock started on leave
    assert len(bg.tasks) == 1


@pytest.mark.asyncio
async def test_default_path_no_clock_when_already_started():
    bot = {"id": "db1", "candidate_round_id": "cr1", "feedback_started_at": "2025-01-01T00:00:00Z"}
    with patch.object(fc, "get_settings", lambda: _settings(voice=False)), \
         patch.object(fc, "_update_bot", AsyncMock()) as upd:
        await fc.trigger_feedback_collection(bot, "rb1", "participant_leave", _BG())
    assert "feedback_started_at" not in upd.await_args.args[1]


@pytest.mark.asyncio
async def test_update_bot_writes():
    sb = MagicMock()
    builder = MagicMock()
    builder.update.return_value = builder
    builder.eq.return_value = builder
    builder.execute_async = AsyncMock(return_value=MagicMock(data=[]))
    sb.table.return_value = builder
    with patch.object(fc, "get_supabase_admin_client", return_value=sb):
        await fc._update_bot("db1", {"feedback_status": "collecting"})
    builder.update.assert_called_once_with({"feedback_status": "collecting"})


@pytest.mark.asyncio
async def test_get_recall_bot_by_recall_id_found_and_missing():
    sb = MagicMock()
    builder = MagicMock()
    builder.select.return_value = builder
    builder.eq.return_value = builder
    builder.execute_async = AsyncMock(return_value=MagicMock(data=[{"id": "db1"}]))
    sb.table.return_value = builder
    with patch.object(fc, "get_supabase_admin_client", return_value=sb):
        assert (await fc.get_recall_bot_by_recall_id("rb1")) == {"id": "db1"}

    builder.execute_async = AsyncMock(return_value=MagicMock(data=[]))
    with patch.object(fc, "get_supabase_admin_client", return_value=sb):
        assert (await fc.get_recall_bot_by_recall_id("rb1")) is None
