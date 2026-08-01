"""Characterization tests for recall_webhook.chat_handler.

Covers the "Scout on"/"yes" trigger detection, the guard branches in
handle_chat_message, the scorecard-question sender, and the chat-message
truncation helper.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.recall_webhook import chat_handler
from app.services.recall_webhook.chat_handler import (
    _format_question_for_chat,
    handle_chat_message,
    is_assistant_on_command,
    send_feedback_prompt,
    send_scorecard_questions,
)


# ----------------------- is_assistant_on_command -----------------------

@pytest.mark.parametrize("msg", ["Scout on", "scot on", "SCOUTON", "  scout  on  ", "scout-on"])
def test_assistant_on_variants_true(msg):
    assert is_assistant_on_command(msg) is True


@pytest.mark.parametrize("msg", ["", "hello", "turn scout off", "scot"])
def test_assistant_on_false(msg):
    assert is_assistant_on_command(msg) is False


# ----------------------- handle_chat_message guards -----------------------

@pytest.mark.asyncio
async def test_handle_chat_unknown_bot_returns():
    with patch.object(chat_handler, "get_recall_bot_by_recall_id", AsyncMock(return_value=None)):
        await handle_chat_message("rb1", {}, MagicMock())  # no exception == pass


@pytest.mark.asyncio
async def test_handle_chat_voice_active_ignored():
    bot = {"feedback_status": "voice_active"}
    trigger = AsyncMock()
    with patch.object(chat_handler, "get_recall_bot_by_recall_id", AsyncMock(return_value=bot)), \
         patch.object(chat_handler, "trigger_feedback_collection", trigger):
        await handle_chat_message("rb1", {}, MagicMock())
    trigger.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_chat_non_waiting_status_ignored():
    bot = {"feedback_status": "completed"}
    trigger = AsyncMock()
    with patch.object(chat_handler, "get_recall_bot_by_recall_id", AsyncMock(return_value=bot)), \
         patch.object(chat_handler, "trigger_feedback_collection", trigger):
        await handle_chat_message("rb1", {}, MagicMock())
    trigger.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_chat_assistant_on_triggers():
    bot = {"feedback_status": "waiting_for_leave"}
    trigger = AsyncMock()
    payload = {"data": {"data": {"text": "Scout on"}}}
    bg = MagicMock()
    with patch.object(chat_handler, "get_recall_bot_by_recall_id", AsyncMock(return_value=bot)), \
         patch.object(chat_handler, "trigger_feedback_collection", trigger):
        await handle_chat_message("rb1", payload, bg)
    trigger.assert_awaited_once_with(bot, "rb1", "chat_command", bg)


@pytest.mark.asyncio
async def test_handle_chat_yes_triggers_only_when_waiting_for_yes():
    bot = {"feedback_status": "waiting_for_yes"}
    trigger = AsyncMock()
    payload = {"data": {"data": {"text": "yes"}}}
    with patch.object(chat_handler, "get_recall_bot_by_recall_id", AsyncMock(return_value=bot)), \
         patch.object(chat_handler, "trigger_feedback_collection", trigger):
        await handle_chat_message("rb1", payload, MagicMock())
    trigger.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_chat_non_trigger_message_ignored():
    bot = {"feedback_status": "waiting_for_yes"}
    trigger = AsyncMock()
    payload = {"data": {"data": {"text": "maybe later"}}}
    with patch.object(chat_handler, "get_recall_bot_by_recall_id", AsyncMock(return_value=bot)), \
         patch.object(chat_handler, "trigger_feedback_collection", trigger):
        await handle_chat_message("rb1", payload, MagicMock())
    trigger.assert_not_awaited()


# ----------------------- send_feedback_prompt -----------------------

@pytest.mark.asyncio
async def test_send_feedback_prompt_success():
    svc = MagicMock()
    svc.send_chat_message = AsyncMock()
    svc.close = AsyncMock()
    with patch.object(chat_handler, "get_recall_service", return_value=svc):
        await send_feedback_prompt("rb1")
    svc.send_chat_message.assert_awaited_once()
    svc.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_feedback_prompt_swallows_error_and_closes():
    svc = MagicMock()
    svc.send_chat_message = AsyncMock(side_effect=RuntimeError("recall down"))
    svc.close = AsyncMock()
    with patch.object(chat_handler, "get_recall_service", return_value=svc):
        await send_feedback_prompt("rb1")
    svc.close.assert_awaited_once()  # finally always closes


# ----------------------- send_scorecard_questions -----------------------

@pytest.mark.asyncio
async def test_send_scorecard_no_candidate_round_id_returns():
    # Returns before touching any service.
    await send_scorecard_questions("rb1", "")


def _scorecard_supabase(round_id="r1", questions=None):
    sb = MagicMock()

    def table(name):
        builder = MagicMock()
        for attr in ("select", "eq", "is_null", "order", "update"):
            setattr(builder, attr, MagicMock(return_value=builder))
        if name == "candidate_rounds":
            builder.execute_async = AsyncMock(return_value=MagicMock(data=[{"round_id": round_id}] if round_id else []))
        elif name == "feedback_questions":
            builder.execute_async = AsyncMock(return_value=MagicMock(data=questions or []))
        else:
            builder.execute_async = AsyncMock(return_value=MagicMock(data=[]))
        return builder

    sb.table = MagicMock(side_effect=table)
    return sb


@pytest.mark.asyncio
async def test_send_scorecard_walks_questions_and_marks_completed():
    svc = MagicMock()
    svc.send_chat_message = AsyncMock()
    svc.close = AsyncMock()
    sb = _scorecard_supabase(questions=[
        {"question_number": 1, "heading": "Comms", "description": "How clear?"},
        {"question_number": 2, "heading": "Tech", "description": None},
    ])
    with patch.object(chat_handler, "get_recall_service", return_value=svc), \
         patch.object(chat_handler, "get_supabase_admin_client", return_value=sb), \
         patch.object(chat_handler.asyncio, "sleep", AsyncMock()):
        await send_scorecard_questions("rb1", "cr1")
    # intro + 2 questions + verdict + signoff = 5 chat messages
    assert svc.send_chat_message.await_count == 5
    svc.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_scorecard_no_candidate_round_row():
    svc = MagicMock()
    svc.send_chat_message = AsyncMock()
    svc.close = AsyncMock()
    sb = _scorecard_supabase(round_id=None)
    with patch.object(chat_handler, "get_recall_service", return_value=svc), \
         patch.object(chat_handler, "get_supabase_admin_client", return_value=sb), \
         patch.object(chat_handler.asyncio, "sleep", AsyncMock()):
        await send_scorecard_questions("rb1", "cr1")
    svc.send_chat_message.assert_not_awaited()
    svc.close.assert_awaited_once()


# ----------------------- _format_question_for_chat -----------------------

def test_format_question_no_description():
    out = _format_question_for_chat({"question_number": 3, "heading": "Skill"})
    assert out == "3. Skill:"


def test_format_question_with_description():
    out = _format_question_for_chat({"question_number": 1, "heading": "H", "description": "short desc"})
    assert out == "1. H:\nshort desc"


def test_format_question_truncates_long_description():
    long_desc = "x" * 1000
    out = _format_question_for_chat({"question_number": 1, "heading": "H", "description": long_desc})
    assert len(out) <= 500
    assert out.endswith("...")
