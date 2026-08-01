"""Characterization tests for app/api/v2/services/recall_orchestrator.py.

Covers create_recall_bot_for_cr (success, warning->None, no-row->None,
HTTPException re-raise, generic-error swallow) and cancel_recall_bot_for_cr
(no active bots, cancel ok flips DB, API failure leaves status, always closes).
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v2.services import recall_orchestrator

CR_ID = uuid4()
NOW = datetime.now(timezone.utc)


def _select_supabase(rows):
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("select", "eq", "order", "limit", "in_", "update"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data=rows))
    sb.table = MagicMock(return_value=builder)
    return sb, builder


# ----------------------- create_recall_bot_for_cr -----------------------

@pytest.mark.asyncio
async def test_create_success_returns_bot_dict():
    sb, _ = _select_supabase([{
        "id": "b1", "recall_bot_id": "rb1", "status": "scheduled",
        "meeting_url": "https://meet", "scheduled_at": NOW.isoformat(),
    }])
    schedule = AsyncMock(return_value={"recall_warning": None})
    with patch("app.services.recall_service.schedule_or_replace_recall_bot", schedule), \
         patch.object(recall_orchestrator, "get_supabase_admin_client", return_value=sb):
        result = await recall_orchestrator.create_recall_bot_for_cr(CR_ID, "Alice", "https://meet", NOW)
    assert result["id"] == "b1"
    assert result["recall_bot_id"] == "rb1"


@pytest.mark.asyncio
async def test_create_warning_returns_none():
    schedule = AsyncMock(return_value={"recall_warning": "bad url"})
    with patch("app.services.recall_service.schedule_or_replace_recall_bot", schedule):
        result = await recall_orchestrator.create_recall_bot_for_cr(CR_ID, "Alice", "https://meet", NOW)
    assert result is None


@pytest.mark.asyncio
async def test_create_no_db_row_returns_none():
    sb, _ = _select_supabase([])
    schedule = AsyncMock(return_value={"recall_warning": None})
    with patch("app.services.recall_service.schedule_or_replace_recall_bot", schedule), \
         patch.object(recall_orchestrator, "get_supabase_admin_client", return_value=sb):
        result = await recall_orchestrator.create_recall_bot_for_cr(CR_ID, "Alice", "https://meet", NOW)
    assert result is None


@pytest.mark.asyncio
async def test_create_http_exception_reraised():
    schedule = AsyncMock(side_effect=HTTPException(status_code=409, detail="locked"))
    with patch("app.services.recall_service.schedule_or_replace_recall_bot", schedule):
        with pytest.raises(HTTPException) as exc:
            await recall_orchestrator.create_recall_bot_for_cr(CR_ID, "Alice", "https://meet", NOW)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_generic_error_swallowed():
    schedule = AsyncMock(side_effect=RuntimeError("recall 500"))
    with patch("app.services.recall_service.schedule_or_replace_recall_bot", schedule):
        result = await recall_orchestrator.create_recall_bot_for_cr(CR_ID, "Alice", "https://meet", NOW)
    assert result is None


# ----------------------- cancel_recall_bot_for_cr -----------------------

@pytest.mark.asyncio
async def test_cancel_no_active_bots_returns():
    sb, _ = _select_supabase([])
    with patch.object(recall_orchestrator, "get_supabase_admin_client", return_value=sb):
        await recall_orchestrator.cancel_recall_bot_for_cr(CR_ID)


@pytest.mark.asyncio
async def test_cancel_ok_flips_db_and_closes():
    sb, builder = _select_supabase([{"id": "b1", "recall_bot_id": "rb1", "status": "in_waiting_room"}])
    svc = MagicMock()
    svc.remove_bot_from_call = AsyncMock()
    svc.delete_bot = AsyncMock()
    svc.close = AsyncMock()
    with patch.object(recall_orchestrator, "get_supabase_admin_client", return_value=sb), \
         patch("app.services.recall_service.get_recall_service", return_value=svc), \
         patch("app.services.recall_service.ACTIVE_BOT_STATUSES", ["in_waiting_room", "joining"]):
        await recall_orchestrator.cancel_recall_bot_for_cr(CR_ID)
    svc.remove_bot_from_call.assert_awaited_once()
    svc.delete_bot.assert_awaited_once()
    svc.close.assert_awaited_once()
    # the cancel-status UPDATE ran
    builder.update.assert_any_call({"status": "cancelled"})


@pytest.mark.asyncio
async def test_cancel_api_failure_leaves_status_but_still_closes():
    sb, builder = _select_supabase([{"id": "b1", "recall_bot_id": "rb1", "status": "joining"}])
    svc = MagicMock()
    svc.remove_bot_from_call = AsyncMock(side_effect=RuntimeError("recall down"))
    svc.delete_bot = AsyncMock()
    svc.close = AsyncMock()
    with patch.object(recall_orchestrator, "get_supabase_admin_client", return_value=sb), \
         patch("app.services.recall_service.get_recall_service", return_value=svc), \
         patch("app.services.recall_service.ACTIVE_BOT_STATUSES", ["joining"]):
        await recall_orchestrator.cancel_recall_bot_for_cr(CR_ID)
    svc.close.assert_awaited_once()
    # API cancel failed -> no 'cancelled' update should have been issued
    for call in builder.update.call_args_list:
        assert call.args[0] != {"status": "cancelled"}
