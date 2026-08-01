"""Tests for DebriefInsightService — durable-first Cortex insight write-back (§6).

Order matters: the row is persisted (sync_status='pending') BEFORE the Cortex
forward, and a dedup pre-check on (packet_id, content_hash) means a duplicate
confirm never inserts again or calls Cortex again. Cortex success flips the row to
'synced'; any Cortex failure leaves it 'pending' and NEVER raises to the caller
(the recruiter's confirm must still succeed).

The Supabase admin client + the CortexInsightClient are mocked.
"""
from __future__ import annotations

import hashlib

import pytest

from app.api.v2.core.exceptions import UpstreamServiceError
from app.services.debrief_chat.insight_service import DebriefInsightService
from app.services.supabase import PostgrestError

PACKET_ID = "00000000-0000-0000-0000-0000000000f1"
REQ_ID = "00000000-0000-0000-0000-000000000020"
ORG_ID = "00000000-0000-0000-0000-000000000010"
USER_ID = "00000000-0000-0000-0000-000000000001"
CAND_ID = "00000000-0000-0000-0000-0000000000a1"
NEW_ROW_ID = "00000000-0000-0000-0000-0000000000d1"


class _Resp:
    def __init__(self, data):
        self.data = data


class _Builder:
    """Records terminal execute_async() results in call order."""

    def __init__(self, table, op, journal, result):
        self._table = table
        self._op = op
        self._journal = journal
        self._result = result

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def single(self):
        return self

    def insert(self, data):
        self._op = "insert"
        self._data = data
        return self

    def update(self, data):
        self._op = "update"
        self._data = data
        return self

    async def execute_async(self):
        self._journal.append(
            {"table": self._table, "op": self._op, "data": getattr(self, "_data", None)}
        )
        return self._result


class _FakeSupabase:
    """A scripted supabase admin client.

    `select_result` is what the dedup pre-check returns (None = no existing row).
    A list of `select_result`s is consumed in order, letting a test script a
    pre-check miss followed by a conflict re-read hit.
    `insert_result` / `update_result` are the terminal results for those ops.
    `insert_raises`, when set, is raised from the insert's execute_async (the
    concurrent-confirm race). All ops are appended to `journal`."""

    def __init__(
        self,
        *,
        select_result,
        insert_result=None,
        update_result=None,
        insert_raises=None,
    ):
        if isinstance(select_result, list):
            self._select_results = list(select_result)
        else:
            self._select_results = [select_result]
        self._insert_result = insert_result or _Resp({"id": NEW_ROW_ID})
        self._update_result = update_result or _Resp({"id": NEW_ROW_ID})
        self._insert_raises = insert_raises
        self.journal = []

    def _next_select_result(self):
        if len(self._select_results) > 1:
            return self._select_results.pop(0)
        return self._select_results[0]

    def table(self, name):
        # The op is resolved by which builder method gets called; default to select.
        return _ScriptedTable(self, name)


class _ScriptedTable:
    def __init__(self, parent, name):
        self._parent = parent
        self._name = name
        self._mode = "select"
        self._data = None

    def select(self, *a, **k):
        self._mode = "select"
        return self

    def eq(self, *a, **k):
        return self

    def single(self):
        return self

    def insert(self, data):
        self._mode = "insert"
        self._data = data
        return self

    def update(self, data):
        self._mode = "update"
        self._data = data
        return self

    async def execute_async(self):
        self._parent.journal.append(
            {"table": self._name, "op": self._mode, "data": self._data}
        )
        if self._mode == "select":
            return self._parent._next_select_result()
        if self._mode == "insert":
            if self._parent._insert_raises is not None:
                raise self._parent._insert_raises
            return self._parent._insert_result
        return self._parent._update_result


class _FakeCortex:
    def __init__(self, *, raises=None):
        self._raises = raises
        self.calls = []

    async def ingest(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise self._raises


def _service(supabase, cortex):
    return DebriefInsightService(supabase, cortex)


async def _log(svc, **over):
    base = dict(
        packet_id=PACKET_ID,
        requisition_id=REQ_ID,
        organization_id=ORG_ID,
        created_by=USER_ID,
        candidate_id=CAND_ID,
        kind="decision_rationale",
        text="Ada won on system design.",
        triplet=None,
    )
    base.update(over)
    return await svc.log(**base)


def _expected_hash(text, kind, candidate_id):
    norm = " ".join(text.split()).strip().lower()
    raw = f"{kind}|{candidate_id or ''}|{norm}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Durable-first: row inserted (pending) BEFORE the Cortex call.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_durable_first_insert_before_cortex():
    supabase = _FakeSupabase(select_result=_Resp(None))
    cortex = _FakeCortex()
    out = await _log(_service(supabase, cortex))

    ops = [j["op"] for j in supabase.journal]
    # select (dedup check) -> insert (pending) -> [cortex] -> update (synced)
    assert ops[0] == "select"
    assert ops[1] == "insert"
    # The insert persisted pending, and it happened before any cortex call.
    insert_data = supabase.journal[1]["data"]
    assert insert_data["sync_status"] == "pending"
    assert insert_data["content_hash"] == _expected_hash(
        "Ada won on system design.", "decision_rationale", CAND_ID
    )
    assert len(cortex.calls) == 1
    assert out["ok"] is True


# ---------------------------------------------------------------------------
# Cortex success -> sync_status flips to 'synced'.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cortex_success_marks_synced():
    supabase = _FakeSupabase(select_result=_Resp(None))
    cortex = _FakeCortex()
    out = await _log(_service(supabase, cortex))

    update_op = next(j for j in supabase.journal if j["op"] == "update")
    assert update_op["data"]["sync_status"] == "synced"
    assert out["sync_status"] == "synced"
    assert out["insight_id"] == NEW_ROW_ID
    # The cortex call got the right contract args.
    call = cortex.calls[0]
    assert call["org_id"] == ORG_ID
    assert call["requisition_id"] == REQ_ID
    assert call["candidate_id"] == CAND_ID
    assert call["kind"] == "decision_rationale"
    assert call["insight_text"] == "Ada won on system design."


# ---------------------------------------------------------------------------
# Cortex raises -> row stays pending, NO exception to caller.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cortex_failure_stays_pending_no_raise():
    supabase = _FakeSupabase(select_result=_Resp(None))
    cortex = _FakeCortex(raises=UpstreamServiceError("cortex down"))
    out = await _log(_service(supabase, cortex))  # must NOT raise

    assert out["ok"] is True
    assert out["sync_status"] == "pending"
    # No update to 'synced' was issued (the only writes are the pending insert).
    update_ops = [j for j in supabase.journal if j["op"] == "update"]
    assert update_ops == []


# ---------------------------------------------------------------------------
# Dedup: a duplicate confirm -> no second insert, no second Cortex call.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dedup_skips_insert_and_cortex():
    existing = _Resp({"id": "existing-row", "sync_status": "synced"})
    supabase = _FakeSupabase(select_result=existing)
    cortex = _FakeCortex()
    out = await _log(_service(supabase, cortex))

    ops = [j["op"] for j in supabase.journal]
    assert ops == ["select"]  # only the dedup pre-check ran
    assert cortex.calls == []  # no second Cortex forward
    assert out["ok"] is True
    assert out["insight_id"] == "existing-row"
    assert out["sync_status"] == "synced"


# ---------------------------------------------------------------------------
# Org-level / candidate-less insight: candidate_id None flows through cleanly.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_org_level_insight_no_candidate():
    supabase = _FakeSupabase(select_result=_Resp(None))
    cortex = _FakeCortex()
    out = await _log(
        _service(supabase, cortex),
        candidate_id=None,
        kind="recruiter_preference",
        text="This team weights system design.",
        triplet={"subject": "PM", "predicate": "values", "object": "system design"},
    )
    insert_data = supabase.journal[1]["data"]
    assert insert_data["candidate_id"] is None
    assert insert_data["triplet"] == {
        "subject": "PM",
        "predicate": "values",
        "object": "system design",
    }
    assert cortex.calls[0]["triplet"] == {
        "subject": "PM",
        "predicate": "values",
        "object": "system design",
    }
    assert out["ok"] is True


# ---------------------------------------------------------------------------
# Concurrent confirms: pre-check misses for BOTH, the loser's insert hits the
# uq_debrief_insight_dedup unique constraint -> swallowed as idempotent success,
# the re-read returns the winner's row, and Cortex is NOT called again.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_insert_unique_violation_is_idempotent():
    winner_row = _Resp({"id": "winner-row", "sync_status": "synced"})
    supabase = _FakeSupabase(
        select_result=[_Resp(None), winner_row],
        insert_raises=PostgrestError(
            message='duplicate key value violates unique constraint '
            '"uq_debrief_insight_dedup"',
            code="23505",
            details="Key (packet_id, content_hash)=(x, y) already exists.",
        ),
    )
    cortex = _FakeCortex()
    out = await _log(_service(supabase, cortex))  # must NOT raise

    assert out["ok"] is True
    assert out["insight_id"] == "winner-row"
    assert out["sync_status"] == "synced"
    # The winner's Cortex forward covers it; the loser must NOT call Cortex.
    assert cortex.calls == []
    ops = [j["op"] for j in supabase.journal]
    # select (miss) -> insert (conflict) -> select (re-read); never an update.
    assert ops == ["select", "insert", "select"]


# ---------------------------------------------------------------------------
# Any OTHER PostgrestError on insert (not the dedup conflict) must propagate.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_insert_other_error_propagates():
    supabase = _FakeSupabase(
        select_result=_Resp(None),
        insert_raises=PostgrestError(
            message="foreign key violation",
            code="23503",
            details="Key (requisition_id)=(z) is not present in table.",
        ),
    )
    cortex = _FakeCortex()
    with pytest.raises(PostgrestError):
        await _log(_service(supabase, cortex))
    assert cortex.calls == []
