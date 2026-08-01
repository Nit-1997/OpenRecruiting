"""Tests for the intake v2 feature flag service."""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.intake_v2_feature_flag import is_intake_v2_enabled


def _client_returning(data):
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute_async = AsyncMock(
        return_value=MagicMock(data=data)
    )
    return sb


@pytest.mark.asyncio
async def test_is_enabled_returns_true_when_org_flag_on():
    sb = _client_returning({"intake_v2_features": {"intake_v2_enabled": True}})
    assert await is_intake_v2_enabled(sb, org_id=uuid4()) is True


@pytest.mark.asyncio
async def test_is_enabled_returns_false_when_flag_missing():
    sb = _client_returning({"intake_v2_features": {}})
    assert await is_intake_v2_enabled(sb, org_id=uuid4()) is False


@pytest.mark.asyncio
async def test_is_enabled_returns_false_when_column_null():
    sb = _client_returning({"intake_v2_features": None})
    assert await is_intake_v2_enabled(sb, org_id=uuid4()) is False


@pytest.mark.asyncio
async def test_is_enabled_returns_false_when_org_not_found():
    sb = _client_returning(None)
    assert await is_intake_v2_enabled(sb, org_id=uuid4()) is False
