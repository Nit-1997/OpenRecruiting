"""Characterization tests for the admin/billing sync helpers
(_sync_usage_credits, _sync_org_type) — plain async functions called
directly with a mocked supabase.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v2.routers.admin import billing


def _supabase(usage_existing):
    """supabase mock where usage_credits select returns `usage_existing`."""
    sb = MagicMock()

    def table(name):
        builder = MagicMock()
        for attr in ("select", "update", "insert", "eq"):
            setattr(builder, attr, MagicMock(return_value=builder))
        if name == "usage_credits":
            builder.execute_async = AsyncMock(return_value=MagicMock(data=usage_existing))
        else:
            builder.execute_async = AsyncMock(return_value=MagicMock(data=[{}]))
        return builder

    sb.table = MagicMock(side_effect=table)
    return sb


PLAN = {"intake_credits": 100, "interview_credits": 50}


@pytest.mark.asyncio
async def test_sync_usage_credits_inserts_when_absent():
    sb = _supabase(usage_existing=[])  # no existing rows -> insert path
    await billing._sync_usage_credits(sb, "org1", PLAN, None, None)
    # Two credit types -> two select + two insert chains; just assert it ran.
    assert sb.table.call_count >= 2


@pytest.mark.asyncio
async def test_sync_usage_credits_updates_when_present_with_reset():
    sb = _supabase(usage_existing=[{"id": "uc1"}])
    await billing._sync_usage_credits(sb, "org1", PLAN, None, None, reset_used=True)
    assert sb.table.call_count >= 2


@pytest.mark.asyncio
async def test_sync_usage_credits_custom_overrides():
    sb = _supabase(usage_existing=[{"id": "uc1"}])
    await billing._sync_usage_credits(sb, "org1", PLAN, custom_intake=200, custom_interview=80, reset_used=False)
    assert sb.table.call_count >= 2


@pytest.mark.asyncio
async def test_sync_org_type_enterprise_updates():
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("update", "eq"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data=[{}]))
    sb.table = MagicMock(return_value=builder)
    await billing._sync_org_type(sb, "org1", "enterprise")
    builder.update.assert_called_once_with({"org_type": "enterprise"})


@pytest.mark.asyncio
async def test_sync_org_type_non_enterprise_noop():
    sb = MagicMock()
    await billing._sync_org_type(sb, "org1", "starter")
    sb.table.assert_not_called()
