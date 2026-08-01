"""Characterization tests for the bot_status_handler helpers:
_load_bot, _on_in_call_recording (credit CAS), _charge_interview_credit,
_resolve_org_id, _rollback_cr_to_scheduled.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.recall_webhook import bot_status_handler as bsh


def _table_supabase(table_results):
    sb = MagicMock()

    def table(name):
        builder = MagicMock()
        for attr in ("select", "update", "eq", "in_"):
            setattr(builder, attr, MagicMock(return_value=builder))
        builder.execute_async = AsyncMock(return_value=table_results.get(name, MagicMock(data=[])))
        return builder

    sb.table = MagicMock(side_effect=table)
    return sb


def _res(data):
    return MagicMock(data=data)


# ----------------------- _load_bot -----------------------

@pytest.mark.asyncio
async def test_load_bot_found_and_missing():
    sb = _table_supabase({"recall_bots": _res([{"id": "db1"}])})
    assert (await bsh._load_bot(sb, "rb1")) == {"id": "db1"}
    sb2 = _table_supabase({"recall_bots": _res([])})
    assert (await bsh._load_bot(sb2, "rb1")) is None


# ----------------------- _rollback_cr_to_scheduled -----------------------

@pytest.mark.asyncio
async def test_rollback_no_cr_id():
    sb = _table_supabase({})
    assert (await bsh._rollback_cr_to_scheduled(sb, None)) is False


@pytest.mark.asyncio
async def test_rollback_flips_when_rows_match():
    sb = _table_supabase({"candidate_rounds": _res([{"id": "cr1"}])})
    assert (await bsh._rollback_cr_to_scheduled(sb, "cr1")) is True


@pytest.mark.asyncio
async def test_rollback_noop_when_no_rows():
    sb = _table_supabase({"candidate_rounds": _res([])})
    assert (await bsh._rollback_cr_to_scheduled(sb, "cr1")) is False


# ----------------------- _resolve_org_id -----------------------

@pytest.mark.asyncio
async def test_resolve_org_id_walks_relations():
    row = {"candidates": {"requisition_id": "r1", "requisitions": {"organization_id": "org1"}}}
    sb = _table_supabase({"candidate_rounds": _res([row])})
    assert (await bsh._resolve_org_id(sb, "cr1")) == "org1"


@pytest.mark.asyncio
async def test_resolve_org_id_no_row():
    sb = _table_supabase({"candidate_rounds": _res([])})
    assert (await bsh._resolve_org_id(sb, "cr1")) is None


@pytest.mark.asyncio
async def test_resolve_org_id_missing_relations():
    sb = _table_supabase({"candidate_rounds": _res([{"candidates": None}])})
    assert (await bsh._resolve_org_id(sb, "cr1")) is None


# ----------------------- _charge_interview_credit -----------------------

@pytest.mark.asyncio
async def test_charge_credit_no_org_skips():
    sb = _table_supabase({"candidate_rounds": _res([])})
    with patch("app.services.credit_service.use_credit", AsyncMock()) as uc:
        await bsh._charge_interview_credit(sb, "cr1", "bot1")
    uc.assert_not_awaited()


@pytest.mark.asyncio
async def test_charge_credit_uses_credit():
    row = {"candidates": {"requisitions": {"organization_id": "org1"}}}
    sb = _table_supabase({"candidate_rounds": _res([row])})
    with patch("app.services.credit_service.use_credit", AsyncMock()) as uc:
        await bsh._charge_interview_credit(sb, "cr1", "bot1")
    uc.assert_awaited_once_with("org1", "interview")


@pytest.mark.asyncio
async def test_charge_credit_failure_swallowed():
    row = {"candidates": {"requisitions": {"organization_id": "org1"}}}
    sb = _table_supabase({"candidate_rounds": _res([row])})
    with patch("app.services.credit_service.use_credit", AsyncMock(side_effect=RuntimeError("no credits"))):
        await bsh._charge_interview_credit(sb, "cr1", "bot1")  # no raise


# ----------------------- _on_in_call_recording -----------------------

@pytest.mark.asyncio
async def test_on_in_call_recording_transitions_and_charges():
    recall_bot = {"id": "db1", "candidate_round_id": "cr1", "credit_charged": False}
    # candidate_rounds update returns rows (transition), CAS on recall_bots wins,
    # org resolution returns org1.
    org_row = {"candidates": {"requisitions": {"organization_id": "org1"}}}

    sb = MagicMock()
    cr_calls = {"n": 0}

    def table(name):
        builder = MagicMock()
        for attr in ("select", "update", "eq", "in_"):
            setattr(builder, attr, MagicMock(return_value=builder))
        if name == "candidate_rounds":
            async def exec_async():
                cr_calls["n"] += 1
                # 1st call: the status transition update -> rows; 2nd: org resolution select
                if cr_calls["n"] == 1:
                    return MagicMock(data=[{"id": "cr1"}])
                return MagicMock(data=[org_row])
            builder.execute_async = AsyncMock(side_effect=exec_async)
        elif name == "recall_bots":
            builder.execute_async = AsyncMock(return_value=MagicMock(data=[{"id": "db1"}]))  # CAS won
        else:
            builder.execute_async = AsyncMock(return_value=MagicMock(data=[]))
        return builder

    sb.table = MagicMock(side_effect=table)
    update_data: dict = {}
    with patch("app.services.credit_service.use_credit", AsyncMock()) as uc:
        transitioned = await bsh._on_in_call_recording(sb, recall_bot, update_data, "2025-01-01T00:00:00Z", "bot1")
    assert transitioned is True
    assert update_data["feedback_status"] == "waiting_for_leave"
    assert update_data["credit_charged"] is True
    uc.assert_awaited_once_with("org1", "interview")


@pytest.mark.asyncio
async def test_on_in_call_recording_already_charged_skips_cas():
    recall_bot = {"id": "db1", "candidate_round_id": "cr1", "credit_charged": True}
    sb = _table_supabase({"candidate_rounds": _res([{"id": "cr1"}])})
    update_data: dict = {}
    with patch("app.services.credit_service.use_credit", AsyncMock()) as uc:
        transitioned = await bsh._on_in_call_recording(sb, recall_bot, update_data, "2025-01-01T00:00:00Z", "bot1")
    assert transitioned is True
    assert "credit_charged" not in update_data  # CAS path skipped
    uc.assert_not_awaited()
