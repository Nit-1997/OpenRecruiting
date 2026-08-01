"""Behavioral tests for CandidateService.add_candidate — the requisition/plan
validation, duplicate-email guard, candidate insert, and per-round
candidate_rounds fan-out.

`self.supabase` is replaced with a per-table fluent stub; `insert_many` is
patched to a chainable builder so the bulk candidate_rounds insert returns the
new rows.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.services.candidate_service as cand_mod
from app.services.candidate_service import CandidateService


def _make_service():
    with patch.object(cand_mod, "get_supabase_admin_client", return_value=MagicMock()):
        return CandidateService()


def _resp(data):
    return MagicMock(data=data)


class _Table:
    """Fluent supabase table stub whose execute_async returns the response keyed
    by table name, and toggled for the candidates table (existence vs insert)."""

    def __init__(self, name, responses):
        self._name = name
        self._responses = responses
        self._is_insert = False

    def select(self, *a, **k):
        return self

    def insert(self, *a, **k):
        self._is_insert = True
        return self

    def eq(self, *a, **k):
        return self

    def is_null(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def single(self):
        return self

    async def execute_async(self):
        if self._name == "candidates":
            key = "candidates_insert" if self._is_insert else "candidates_existing"
            return _resp(self._responses[key])
        return _resp(self._responses[self._name])


class _Supa:
    def __init__(self, responses):
        self._responses = responses

    def table(self, name):
        return _Table(name, self._responses)


def _patch_insert_many(cr_rows_response):
    """insert_many(client, table, rows) -> builder with awaitable execute_async."""
    builder = MagicMock()
    builder.execute_async = AsyncMock(return_value=_resp(cr_rows_response))
    return MagicMock(return_value=builder)


async def test_add_candidate_happy_path():
    svc = _make_service()
    responses = {
        "requisitions": {"id": "req-1", "role_title": "Engineer", "status": "open"},
        "rounds": [
            {"id": "r1", "name": "Phone", "round_number": 1},
            {"id": "r2", "name": "Onsite", "round_number": 2},
        ],
        "candidates_existing": [],
        "candidates_insert": {"id": "cand-1", "name": "Jane", "email": "jane@x.com"},
    }
    svc.supabase = _Supa(responses)

    cr_rows = [
        {"id": "cr1", "round_id": "r1"},
        {"id": "cr2", "round_id": "r2"},
    ]
    with patch.object(cand_mod, "insert_many", _patch_insert_many(cr_rows)):
        result = await svc.add_candidate(
            requisition_id="req-1", org_id="o1", name="Jane", email="jane@x.com"
        )

    assert result["candidate"]["id"] == "cand-1"
    assert result["role_title"] == "Engineer"
    assert len(result["rounds"]) == 2
    by_id = {r["id"]: r for r in result["rounds"]}
    assert by_id["r1"]["candidate_round_id"] == "cr1"
    assert by_id["r2"]["candidate_round_id"] == "cr2"


async def test_add_candidate_requisition_not_found():
    svc = _make_service()
    responses = {
        "requisitions": None,
        "rounds": [],
        "candidates_existing": [],
        "candidates_insert": None,
    }
    svc.supabase = _Supa(responses)
    with pytest.raises(ValueError, match="Requisition not found"):
        await svc.add_candidate(requisition_id="req-x", org_id="o1", name="J", email="j@x.com")


async def test_add_candidate_no_rounds_requires_plan():
    svc = _make_service()
    responses = {
        "requisitions": {"id": "req-1", "role_title": "Eng", "status": "open"},
        "rounds": [],
        "candidates_existing": [],
        "candidates_insert": None,
    }
    svc.supabase = _Supa(responses)
    with pytest.raises(ValueError, match="no interview plan"):
        await svc.add_candidate(requisition_id="req-1", org_id="o1", name="J", email="j@x.com")


async def test_add_candidate_duplicate_email_rejected():
    svc = _make_service()
    responses = {
        "requisitions": {"id": "req-1", "role_title": "Eng", "status": "open"},
        "rounds": [{"id": "r1", "name": "Phone", "round_number": 1}],
        "candidates_existing": [{"id": "existing-cand"}],
        "candidates_insert": None,
    }
    svc.supabase = _Supa(responses)
    with pytest.raises(ValueError, match="already exists"):
        await svc.add_candidate(requisition_id="req-1", org_id="o1", name="J", email="dupe@x.com")


async def test_add_candidate_insert_failure_raises():
    svc = _make_service()
    responses = {
        "requisitions": {"id": "req-1", "role_title": "Eng", "status": "open"},
        "rounds": [{"id": "r1", "name": "Phone", "round_number": 1}],
        "candidates_existing": [],
        "candidates_insert": None,  # insert returned no data -> failure
    }
    svc.supabase = _Supa(responses)
    with pytest.raises(ValueError, match="Failed to create candidate"):
        await svc.add_candidate(requisition_id="req-1", org_id="o1", name="J", email="j@x.com")
