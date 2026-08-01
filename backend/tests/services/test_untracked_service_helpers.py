"""Characterization tests for untracked_service helper functions:
_first, _to_int, _initials, _now_iso, _load_source_round, _load_candidate,
_assert_source_in_org, _cancel_round_best_effort.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v2.services import untracked_service as us
from app.api.v2.services.untracked_service import UntrackedMutationError


# ----------------------- pure helpers -----------------------

def test_first_list_dict_none():
    assert us._first([{"a": 1}, {"b": 2}]) == {"a": 1}
    assert us._first([]) is None
    assert us._first({"x": 1}) == {"x": 1}
    assert us._first(None) is None
    assert us._first("str") is None


def test_to_int():
    assert us._to_int(None) == 0
    assert us._to_int("5") == 5
    assert us._to_int(7) == 7
    assert us._to_int("nope") == 0


def test_duration_minutes():
    # computed from event_start/event_end (no event_duration_minutes column)
    assert us._duration_minutes("2026-06-04T08:00:00+00:00", "2026-06-04T08:45:00+00:00") == 45
    assert us._duration_minutes("2026-06-04T08:00:00+00:00", "2026-06-04T08:00:00+00:00") == 0
    assert us._duration_minutes(None, "2026-06-04T08:45:00+00:00") == 0
    assert us._duration_minutes("2026-06-04T08:00:00+00:00", None) == 0
    assert us._duration_minutes("garbage", "also-garbage") == 0
    # end before start clamps to 0
    assert us._duration_minutes("2026-06-04T09:00:00+00:00", "2026-06-04T08:00:00+00:00") == 0


def test_initials():
    assert us._initials("Alice Smith") == "AS"
    assert us._initials("Alice") == "A"
    assert us._initials("a b c d") == "AB"
    assert us._initials("") == "?"


def test_now_iso_is_string():
    assert isinstance(us._now_iso(), str)


# ----------------------- loaders -----------------------

def _single_table_supabase(data):
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("select", "eq", "limit"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data=data))
    sb.table = MagicMock(return_value=builder)
    return sb


@pytest.mark.asyncio
async def test_load_source_round_not_found():
    sb = _single_table_supabase([])
    with pytest.raises(UntrackedMutationError) as exc:
        await us._load_source_round(sb, "cr1")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_load_source_round_wrong_source_type():
    sb = _single_table_supabase([{"id": "cr1", "source_type": "scheduled"}])
    with pytest.raises(UntrackedMutationError) as exc:
        await us._load_source_round(sb, "cr1")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_load_source_round_ok():
    sb = _single_table_supabase([{"id": "cr1", "source_type": "untracked_generic", "candidate_id": "c1"}])
    row = await us._load_source_round(sb, "cr1")
    assert row["id"] == "cr1"


@pytest.mark.asyncio
async def test_load_candidate_not_found():
    sb = _single_table_supabase([])
    with pytest.raises(UntrackedMutationError) as exc:
        await us._load_candidate(sb, "c1")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_load_candidate_ok():
    sb = _single_table_supabase([{"id": "c1", "name": "Alice"}])
    row = await us._load_candidate(sb, "c1")
    assert row["name"] == "Alice"


@pytest.mark.asyncio
async def test_assert_source_in_org_forbidden_wrong_org():
    sb = _single_table_supabase([{"id": "r1", "organization_id": "OTHER", "is_system_template": True}])
    with pytest.raises(UntrackedMutationError) as exc:
        await us._assert_source_in_org(sb, "r1", "org1")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_assert_source_in_org_not_system_template():
    sb = _single_table_supabase([{"id": "r1", "organization_id": "org1", "is_system_template": False}])
    with pytest.raises(UntrackedMutationError) as exc:
        await us._assert_source_in_org(sb, "r1", "org1")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_assert_source_in_org_ok():
    sb = _single_table_supabase([{"id": "r1", "organization_id": "org1", "is_system_template": True}])
    await us._assert_source_in_org(sb, "r1", "org1")  # no raise


# ----------------------- side-effect helpers -----------------------

@pytest.mark.asyncio
async def test_cancel_round_best_effort_swallows_error():
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("update", "eq"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(side_effect=RuntimeError("db down"))
    sb.table = MagicMock(return_value=builder)
    await us._cancel_round_best_effort(sb, "cr1")  # no raise


@pytest.mark.asyncio
async def test_cancel_round_best_effort_ok():
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("update", "eq"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data=[{}]))
    sb.table = MagicMock(return_value=builder)
    await us._cancel_round_best_effort(sb, "cr1")
