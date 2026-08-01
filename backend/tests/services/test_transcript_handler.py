"""Characterization tests for recall_webhook.transcript_handler.

Covers the disabled gate, the no-text/unknown-bot early returns, the
threshold-not-met path, the detection-enqueue path, the bot-id cache resolver,
and the _run_detection_and_handle background task (store + retroactive trigger).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.recall_webhook import (
    participant_handler,
    transcript_handler,
)


@pytest.fixture(autouse=True)
def _clear_module_state():
    transcript_handler._bot_id_map.clear()
    participant_handler._detection_in_flight.clear()
    yield
    transcript_handler._bot_id_map.clear()
    participant_handler._detection_in_flight.clear()


def _settings(enabled=True, char=10, min_p=2):
    return SimpleNamespace(
        CANDIDATE_DETECT_ENABLED=enabled,
        CANDIDATE_DETECT_CHAR_THRESHOLD=char,
        CANDIDATE_DETECT_MIN_PARTICIPANTS=min_p,
    )


def _payload(pid="p1", text="hello there everyone"):
    words = [{"text": w} for w in text.split()]
    return {"data": {"participant": {"id": pid}, "words": words}}


class _BG:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *a, **k):
        self.tasks.append((fn, a, k))


# ----------------------- handle_transcript_data gates -----------------------

@pytest.mark.asyncio
async def test_disabled_returns_immediately():
    with patch.object(transcript_handler, "get_settings", lambda: _settings(enabled=False)):
        await transcript_handler.handle_transcript_data("rb1", _payload(), _BG())


@pytest.mark.asyncio
async def test_no_participant_or_words_returns():
    with patch.object(transcript_handler, "get_settings", lambda: _settings()):
        await transcript_handler.handle_transcript_data("rb1", {"data": {"participant": {}, "words": []}}, _BG())


@pytest.mark.asyncio
async def test_blank_text_returns():
    payload = {"data": {"participant": {"id": "p1"}, "words": [{"text": "  "}]}}
    with patch.object(transcript_handler, "get_settings", lambda: _settings()):
        await transcript_handler.handle_transcript_data("rb1", payload, _BG())


@pytest.mark.asyncio
async def test_unknown_bot_returns():
    with patch.object(transcript_handler, "get_settings", lambda: _settings()), \
         patch.object(transcript_handler, "get_recall_bot_by_recall_id", AsyncMock(return_value=None)):
        await transcript_handler.handle_transcript_data("rb1", _payload(), _BG())
    assert "rb1" not in transcript_handler._bot_id_map


@pytest.mark.asyncio
async def test_threshold_not_met_no_enqueue():
    bg = _BG()
    with patch.object(transcript_handler, "get_settings", lambda: _settings(char=5, min_p=2)), \
         patch.object(transcript_handler, "get_recall_bot_by_recall_id", AsyncMock(return_value={"id": "db1"})), \
         patch.object(transcript_handler, "append_utterance", MagicMock()), \
         patch.object(transcript_handler, "get_utterances", lambda _: {"p1": "only one speaker text"}):
        await transcript_handler.handle_transcript_data("rb1", _payload(), bg)
    assert bg.tasks == []


@pytest.mark.asyncio
async def test_threshold_met_enqueues_detection():
    bg = _BG()
    with patch.object(transcript_handler, "get_settings", lambda: _settings(char=3, min_p=2)), \
         patch.object(transcript_handler, "get_recall_bot_by_recall_id", AsyncMock(return_value={"id": "db1"})), \
         patch.object(transcript_handler, "append_utterance", MagicMock()), \
         patch.object(transcript_handler, "get_utterances", lambda _: {"p1": "aaaa", "p2": "bbbb"}):
        await transcript_handler.handle_transcript_data("rb1", _payload(), bg)
    assert len(bg.tasks) == 1
    assert "db1" in participant_handler._detection_in_flight


@pytest.mark.asyncio
async def test_in_flight_skips_enqueue():
    bg = _BG()
    participant_handler._detection_in_flight.add("db1")
    with patch.object(transcript_handler, "get_settings", lambda: _settings(char=3, min_p=1)), \
         patch.object(transcript_handler, "get_recall_bot_by_recall_id", AsyncMock(return_value={"id": "db1"})), \
         patch.object(transcript_handler, "append_utterance", MagicMock()), \
         patch.object(transcript_handler, "get_utterances", lambda _: {"p1": "aaaa", "p2": "bbbb"}):
        await transcript_handler.handle_transcript_data("rb1", _payload(), bg)
    assert bg.tasks == []


# ----------------------- _resolve_bot_db_id -----------------------

@pytest.mark.asyncio
async def test_resolve_caches_id():
    with patch.object(transcript_handler, "get_recall_bot_by_recall_id", AsyncMock(return_value={"id": "db1"})) as m:
        first = await transcript_handler._resolve_bot_db_id("rb1")
        second = await transcript_handler._resolve_bot_db_id("rb1")
    assert first == second == "db1"
    m.assert_awaited_once()  # second call served from cache


@pytest.mark.asyncio
async def test_resolve_detection_completed_returns_none():
    with patch.object(transcript_handler, "get_recall_bot_by_recall_id", AsyncMock(return_value={"id": "db1", "detection_completed": True})):
        assert await transcript_handler._resolve_bot_db_id("rb1") is None


# ----------------------- _run_detection_and_handle -----------------------

def _fresh_supabase(bot_row):
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("select", "eq", "single", "update"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data=bot_row))
    sb.table = MagicMock(return_value=builder)
    return sb


@pytest.mark.asyncio
async def test_run_detection_no_fresh_row_clears_flight():
    participant_handler._detection_in_flight.add("db1")
    sb = _fresh_supabase(None)
    with patch.object(transcript_handler, "get_supabase_admin_client", return_value=sb):
        await transcript_handler._run_detection_and_handle("rb1", "db1", {})
    assert "db1" not in participant_handler._detection_in_flight


@pytest.mark.asyncio
async def test_run_detection_already_completed_pops_cache():
    transcript_handler._bot_id_map["rb1"] = "db1"
    sb = _fresh_supabase({"id": "db1", "detection_completed": True})
    with patch.object(transcript_handler, "get_supabase_admin_client", return_value=sb):
        await transcript_handler._run_detection_and_handle("rb1", "db1", {})
    assert "rb1" not in transcript_handler._bot_id_map


@pytest.mark.asyncio
async def test_run_detection_stores_and_no_retroactive():
    sb = _fresh_supabase({"id": "db1", "detection_completed": False, "feedback_status": "in_progress"})
    result = {"candidate_participant_id": "p1", "confidence": 0.9}
    with patch.object(transcript_handler, "get_supabase_admin_client", return_value=sb), \
         patch.object(transcript_handler, "run_detection", AsyncMock(return_value=result)), \
         patch.object(transcript_handler, "store_detection_result", AsyncMock()) as store, \
         patch.object(transcript_handler, "check_retroactive_trigger", AsyncMock(return_value=False)):
        await transcript_handler._run_detection_and_handle("rb1", "db1", {"p1": "x"})
    store.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_detection_retroactive_trigger_prompts():
    sb = _fresh_supabase({
        "id": "db1", "detection_completed": False,
        "feedback_status": "waiting_for_leave", "candidate_round_id": "cr1",
        "feedback_started_at": None,
    })
    result = {"candidate_participant_id": "p1", "confidence": 0.95}
    prompt = AsyncMock()
    with patch.object(transcript_handler, "get_supabase_admin_client", return_value=sb), \
         patch.object(transcript_handler, "run_detection", AsyncMock(return_value=result)), \
         patch.object(transcript_handler, "store_detection_result", AsyncMock()), \
         patch.object(transcript_handler, "check_retroactive_trigger", AsyncMock(return_value=True)), \
         patch("app.services.recall_webhook.chat_handler.send_feedback_prompt", prompt):
        await transcript_handler._run_detection_and_handle("rb1", "db1", {"p1": "x"})
    prompt.assert_awaited_once_with("rb1")


@pytest.mark.asyncio
async def test_run_detection_none_result_returns():
    sb = _fresh_supabase({"id": "db1", "detection_completed": False})
    with patch.object(transcript_handler, "get_supabase_admin_client", return_value=sb), \
         patch.object(transcript_handler, "run_detection", AsyncMock(return_value=None)), \
         patch.object(transcript_handler, "store_detection_result", AsyncMock()) as store:
        await transcript_handler._run_detection_and_handle("rb1", "db1", {})
    store.assert_not_awaited()
