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


# ---------------------------------------------------------------------------
# provision_default_credits / set_org_budget
# ---------------------------------------------------------------------------


def _supa_writes(existing_rows):
    """Stub whose reads return `existing_rows` and whose insert/update calls
    are recorded on the builder for assertion."""
    b = MagicMock()
    for m in ("table", "select", "eq", "insert", "update"):
        getattr(b, m).return_value = b
    b.execute_async = AsyncMock(return_value=MagicMock(data=existing_rows))
    supa = MagicMock()
    supa.table.return_value = b
    return supa, b


async def test_provision_grants_both_credit_types_to_new_org():
    supa, b = _supa_writes([])
    with patch.object(credit_mod, "get_supabase_admin_client", return_value=supa):
        await credit_mod.provision_default_credits("org-new")

    inserted = [c.args[0] for c in b.insert.call_args_list]
    assert {row["credit_type"] for row in inserted} == {"intake", "interview"}
    assert all(row["organization_id"] == "org-new" for row in inserted)
    assert all(row["used"] == 0 for row in inserted)
    assert all(row["total"] == 10 for row in inserted)


async def test_provision_is_idempotent_and_never_resets_a_tuned_budget():
    """Re-running against an org that already has rows must not insert or
    overwrite — an admin may have already raised the cap."""
    supa, b = _supa_writes([{"id": "existing"}])
    with patch.object(credit_mod, "get_supabase_admin_client", return_value=supa):
        await credit_mod.provision_default_credits("org-existing")

    b.insert.assert_not_called()
    b.update.assert_not_called()


async def test_provision_swallows_errors_so_org_creation_survives():
    supa, b = _supa_writes([])
    b.execute_async = AsyncMock(side_effect=RuntimeError("supabase down"))
    with patch.object(credit_mod, "get_supabase_admin_client", return_value=supa):
        await credit_mod.provision_default_credits("org-x")  # must not raise


async def test_set_org_budget_updates_existing_row_preserving_used():
    supa, b = _supa_writes([{"id": "row-1"}])
    with patch.object(credit_mod, "get_supabase_admin_client", return_value=supa):
        await credit_mod.set_org_budget("org-1", interview_total=50)

    b.update.assert_called_once_with({"total": 50})
    b.insert.assert_not_called()


async def test_set_org_budget_inserts_when_org_has_no_row_yet():
    supa, b = _supa_writes([])
    with patch.object(credit_mod, "get_supabase_admin_client", return_value=supa):
        await credit_mod.set_org_budget("org-1", intake_total=25)

    b.insert.assert_called_once()
    row = b.insert.call_args.args[0]
    assert row == {
        "organization_id": "org-1",
        "credit_type": "intake",
        "total": 25,
        "used": 0,
        "period_start": "now()",
    }


async def test_set_org_budget_ignores_omitted_credit_types():
    supa, b = _supa_writes([{"id": "row-1"}])
    with patch.object(credit_mod, "get_supabase_admin_client", return_value=supa):
        await credit_mod.set_org_budget("org-1", intake_total=None, interview_total=7)

    b.update.assert_called_once_with({"total": 7})


async def test_set_org_budget_accepts_unlimited_sentinel():
    supa, b = _supa_writes([{"id": "row-1"}])
    with patch.object(credit_mod, "get_supabase_admin_client", return_value=supa):
        await credit_mod.set_org_budget("org-1", interview_total=-1)

    b.update.assert_called_once_with({"total": -1})
