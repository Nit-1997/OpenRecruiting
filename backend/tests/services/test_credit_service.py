"""Behavioral tests for credit_service — the two-tier (monthly + topup) credit
accounting reads and the atomic `use_credit` RPC that raises 402 on exhaustion.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import app.services.credit_service as credit_mod


def _supa_single(execute_result):
    """Stub for the monthly `.single()` read."""
    b = MagicMock()
    for m in ("table", "select", "eq", "single"):
        getattr(b, m).return_value = b
    b.execute_async = AsyncMock(return_value=execute_result)
    supa = MagicMock()
    supa.table.return_value = b
    return supa, b


def _supa_two_reads(monthly, topup):
    """Stub returning `monthly` for the first read and `topup` for the second —
    check_credits issues usage_credits then topup_credits."""
    monthly_b = MagicMock()
    topup_b = MagicMock()
    for b in (monthly_b, topup_b):
        for m in ("select", "eq", "single"):
            getattr(b, m).return_value = b
    monthly_b.execute_async = AsyncMock(return_value=MagicMock(data=monthly))
    topup_b.execute_async = AsyncMock(return_value=MagicMock(data=topup))

    supa = MagicMock()
    supa.table.side_effect = lambda name: monthly_b if name == "usage_credits" else topup_b
    return supa


# ---------------------------------------------------------------------------
# check_credits
# ---------------------------------------------------------------------------


async def test_check_credits_free_default_for_new_org():
    supa, _ = _supa_single(MagicMock(data=None))
    with patch.object(credit_mod, "get_supabase_admin_client", return_value=supa):
        result = await credit_mod.check_credits("o1", "interview")
    assert result["source"] == "free_default"
    assert result["has_credits"] is True
    assert result["monthly_remaining"] == 1


async def test_check_credits_unlimited_enterprise():
    supa, _ = _supa_single(MagicMock(data={"total": -1, "used": 9999}))
    with patch.object(credit_mod, "get_supabase_admin_client", return_value=supa):
        result = await credit_mod.check_credits("o1", "interview")
    assert result["monthly_remaining"] == -1
    assert result["source"] == "monthly"


async def test_check_credits_monthly_remaining():
    supa, _ = _supa_single(MagicMock(data={"total": 10, "used": 4}))
    with patch.object(credit_mod, "get_supabase_admin_client", return_value=supa):
        result = await credit_mod.check_credits("o1", "interview")
    assert result["monthly_remaining"] == 6
    assert result["source"] == "monthly"


async def test_check_credits_falls_back_to_topup():
    supa = _supa_two_reads(
        monthly={"total": 5, "used": 5},  # exhausted
        topup=[{"remaining": 2}, {"remaining": 0}, {"remaining": 3}],
    )
    with patch.object(credit_mod, "get_supabase_admin_client", return_value=supa):
        result = await credit_mod.check_credits("o1", "interview")
    assert result["source"] == "topup"
    assert result["topup_remaining"] == 5
    assert result["has_credits"] is True


async def test_check_credits_none_when_all_exhausted():
    supa = _supa_two_reads(
        monthly={"total": 5, "used": 5},
        topup=[],
    )
    with patch.object(credit_mod, "get_supabase_admin_client", return_value=supa):
        result = await credit_mod.check_credits("o1", "interview")
    assert result["source"] == "none"
    assert result["has_credits"] is False


# ---------------------------------------------------------------------------
# use_credit
# ---------------------------------------------------------------------------


async def test_use_credit_consumes_monthly():
    supa = MagicMock()
    supa.rpc = AsyncMock(return_value=MagicMock(data="monthly"))
    with patch.object(credit_mod, "get_supabase_admin_client", return_value=supa):
        await credit_mod.use_credit("o1", "interview")
    supa.rpc.assert_awaited_once()
    args = supa.rpc.call_args.args
    assert args[0] == "use_credit_atomic"
    assert args[1]["p_org_id"] == "o1"


async def test_use_credit_exhausted_raises_402():
    supa = MagicMock()
    supa.rpc = AsyncMock(return_value=MagicMock(data="exhausted"))
    with patch.object(credit_mod, "get_supabase_admin_client", return_value=supa):
        with pytest.raises(HTTPException) as e:
            await credit_mod.use_credit("o1", "interview")
    assert e.value.status_code == 402
    assert e.value.detail["error"] == "credits_exhausted"
    assert e.value.detail["credit_type"] == "interview"
