"""Unit tests for CandidateDecisionService — org-scoped verdict + outcome writes.

These are the org-scoped recruiter twins of the staff-only admin candidate routes
(spec §4): they re-scope ownership to the caller's org before writing, rather than
leaning on the admin service-role trust. The Supabase admin client is mocked; we
assert org-scope enforcement (cross-org -> NotFoundError), enum validation, and the
update payloads.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v2.core.exceptions import NotFoundError, ValidationError
from app.api.v2.services.candidate_decision_service import CandidateDecisionService

ORG_ID = "00000000-0000-0000-0000-000000000010"
OTHER_ORG = "00000000-0000-0000-0000-0000000000ee"
CAND_ID = "00000000-0000-0000-0000-0000000000a1"
CR_ID = "00000000-0000-0000-0000-0000000000c1"


# ---------------------------------------------------------------------------
# Supabase double: a fluent table().select()...single().execute_async() chain
# plus update()...execute_async(). Each table is configured with the row its
# read returns.
# ---------------------------------------------------------------------------
class _Chain:
    def __init__(self, read_row, update_sink):
        self._read_row = read_row
        self._update_sink = update_sink
        self._is_update = False

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def is_null(self, *a, **k):
        return self

    def single(self):
        return self

    def update(self, payload):
        self._is_update = True
        self._update_sink["payload"] = payload
        return self

    async def execute_async(self):
        result = MagicMock()
        if self._is_update:
            result.data = [{**(self._read_row or {}), **self._update_sink["payload"]}]
        else:
            result.data = self._read_row
        return result


def _supabase(read_row):
    update_sink: dict = {}
    db = MagicMock()
    db.table = MagicMock(return_value=_Chain(read_row, update_sink))
    db._update_sink = update_sink
    return db


def _candidate_row(org=ORG_ID, deleted=None):
    return {
        "id": CAND_ID,
        "requisition_id": "req-1",
        "final_verdict": None,
        "status": "active",
        "requisitions": {"organization_id": org, "deleted_at": deleted},
    }


def _cr_row(org=ORG_ID):
    return {
        "id": CR_ID,
        "candidate_id": CAND_ID,
        "outcome": None,
        "rounds": {"id": "r1", "name": "Onsite", "round_number": 2, "deleted_at": None},
        "candidates": {
            "id": CAND_ID,
            "deleted_at": None,
            "requisitions": {"organization_id": org, "status": "open", "deleted_at": None},
        },
    }


# ---------------------------------------------------------------------------
# set_verdict
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_set_verdict_invalid_enum_raises_validation():
    svc = CandidateDecisionService(_supabase(_candidate_row()))
    with pytest.raises(ValidationError):
        await svc.set_verdict(CAND_ID, "lukewarm", None, ORG_ID)


@pytest.mark.asyncio
async def test_set_verdict_cross_org_raises_not_found():
    svc = CandidateDecisionService(_supabase(_candidate_row(org=OTHER_ORG)))
    with pytest.raises(NotFoundError):
        await svc.set_verdict(CAND_ID, "hire", None, ORG_ID)


@pytest.mark.asyncio
async def test_set_verdict_missing_candidate_raises_not_found():
    svc = CandidateDecisionService(_supabase(None))
    with pytest.raises(NotFoundError):
        await svc.set_verdict(CAND_ID, "hire", None, ORG_ID)


@pytest.mark.asyncio
async def test_set_verdict_happy_path_updates_verdict_only():
    db = _supabase(_candidate_row())
    svc = CandidateDecisionService(db)
    out = await svc.set_verdict(CAND_ID, "strong_hire", None, ORG_ID)
    assert db._update_sink["payload"] == {"final_verdict": "strong_hire"}
    assert out["final_verdict"] == "strong_hire"


@pytest.mark.asyncio
async def test_set_verdict_with_status_updates_both():
    db = _supabase(_candidate_row())
    svc = CandidateDecisionService(db)
    await svc.set_verdict(CAND_ID, "no_hire", "rejected", ORG_ID)
    assert db._update_sink["payload"] == {
        "final_verdict": "no_hire",
        "status": "rejected",
    }


@pytest.mark.asyncio
async def test_set_verdict_invalid_status_enum_raises():
    svc = CandidateDecisionService(_supabase(_candidate_row()))
    with pytest.raises(ValidationError):
        await svc.set_verdict(CAND_ID, "hire", "ghosted", ORG_ID)


# ---------------------------------------------------------------------------
# set_round_outcome
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_set_round_outcome_invalid_enum_raises_validation():
    svc = CandidateDecisionService(_supabase(_cr_row()))
    with pytest.raises(ValidationError):
        await svc.set_round_outcome(CR_ID, "maybe-later", ORG_ID)


@pytest.mark.asyncio
async def test_set_round_outcome_cross_org_raises_not_found():
    svc = CandidateDecisionService(_supabase(_cr_row(org=OTHER_ORG)))
    with pytest.raises(NotFoundError):
        await svc.set_round_outcome(CR_ID, "advance", ORG_ID)


@pytest.mark.asyncio
async def test_set_round_outcome_missing_cr_raises_not_found():
    svc = CandidateDecisionService(_supabase(None))
    with pytest.raises(NotFoundError):
        await svc.set_round_outcome(CR_ID, "advance", ORG_ID)


@pytest.mark.asyncio
async def test_set_round_outcome_happy_path_updates_outcome():
    db = _supabase(_cr_row())
    svc = CandidateDecisionService(db)
    out = await svc.set_round_outcome(CR_ID, "reject", ORG_ID)
    assert db._update_sink["payload"] == {"outcome": "reject"}
    assert out["outcome"] == "reject"
