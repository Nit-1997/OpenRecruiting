"""BE-S5 / UNTRACKED-MA: concurrency-race remediation for untracked link / dismiss.

A same-target double-submit (two concurrent clicks linking to the SAME target)
can both pass the read-then-insert pre-check, producing duplicate import rows,
duplicate candidate_rounds, and a duplicate feedback-Lambda trigger. The
remaining DB guard is `uq_import_source_target` (source, target_requisition_id,
target_round_id), so the loser's import insert raises Postgres unique_violation
(SQLSTATE 23505). These tests prove the service maps that to a clean 409 and
does NOT leave a surviving duplicate candidate_round nor fire feedback twice.
(The source-only single-active index was removed by the multi-attempt model —
single-active across DIFFERENT targets is now maintained by the supersede step,
not the DB. See test_untracked_multi_attempt.py for the reassign semantics.)

The fake supabase is the same table-routed recorder used by
`test_untracked_link_reprocess.py`, extended so a chosen (table, op) insert
raises a PostgrestError(code="23505") to simulate losing the race.
"""

import pytest

import app.api.v2.services.untracked_service as us
from app.services.supabase import PostgrestError


ORG_ID = "org-1"
SOURCE_CR_ID = "src-cr-1"
SOURCE_CAND_ID = "src-cand-1"
SOURCE_REQ_ID = "src-req-1"  # the generic/system requisition
TARGET_REQ_ID = "tgt-req-1"
TARGET_ROUND_ID = "tgt-round-1"
NEW_CAND_ID = "new-cand-1"
NEW_TARGET_CR_ID = "tgt-cr-1"


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, fake, table):
        self._fake = fake
        self._table = table
        self._op = "select"
        self._payload = None

    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    # Filter/ordering methods are no-ops for routing purposes.
    def eq(self, *_a, **_k):
        return self

    def neq(self, *_a, **_k):
        return self

    def ilike(self, *_a, **_k):
        return self

    def is_(self, *_a, **_k):
        return self

    def in_(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    async def execute_async(self):
        key = (self._table, self._op)
        if self._op in ("insert", "update"):
            self._fake.writes.append((self._table, self._op, self._payload))
            if key in self._fake.raise_on:
                raise self._fake.raise_on[key]
            row = dict(self._payload)
            row.setdefault("id", self._fake.insert_ids.get(self._table))
            return _FakeResponse([row])
        queue = self._fake.selects.get(self._table, [])
        data = queue.pop(0) if queue else []
        return _FakeResponse(data)


class _FakeSupabase:
    def __init__(self):
        self.selects = {
            "candidate_rounds": [
                [{
                    "id": SOURCE_CR_ID,
                    "candidate_id": SOURCE_CAND_ID,
                    "round_id": "src-round-1",
                    "source_type": "untracked_generic",
                    "status": "completed",
                    "origin_detection_id": "det-1",
                    "scheduled_at": None,
                    "completed_at": None,
                    "interviewer_email": "iv@test.com",
                    "meeting_url": "https://m",
                    "recording_url": "https://r",
                    "transcript_url": "https://t",
                }],
            ],
            "candidates": [
                [{
                    "id": SOURCE_CAND_ID,
                    "requisition_id": SOURCE_REQ_ID,
                    "name": "Jane",
                    "email": "jane@test.com",
                    "phone": None,
                    "resume_url": None,
                }],
                [],  # _resolve_target_candidate email lookup -> none -> insert
            ],
            "requisitions": [
                [{
                    "id": SOURCE_REQ_ID,
                    "organization_id": ORG_ID,
                    "is_system_template": True,
                }],
                [{
                    "id": TARGET_REQ_ID,
                    "organization_id": ORG_ID,
                    "is_system_template": False,
                }],
            ],
            "untracked_interview_imports": [
                [],  # pre-check: no prior import (the race: pre-check passes)
            ],
            "rounds": [
                [{
                    "id": TARGET_ROUND_ID,
                    "requisition_id": TARGET_REQ_ID,
                    "round_number": 1,
                }],
            ],
        }
        self.insert_ids = {
            "candidates": NEW_CAND_ID,
            "candidate_rounds": NEW_TARGET_CR_ID,
            "untracked_interview_imports": "import-1",
        }
        # (table, op) -> exception to raise from execute_async()
        self.raise_on: dict[tuple[str, str], Exception] = {}
        # ordered (table, op, payload) write log
        self.writes: list[tuple] = []

    def table(self, name):
        return _FakeQuery(self, name)


def _unique_violation() -> PostgrestError:
    return PostgrestError(
        message="duplicate key value violates unique constraint "
        '"uq_import_source_target"',
        code="23505",
    )


def _writes_of(fake, table, op):
    return [w for w in fake.writes if w[0] == table and w[1] == op]


@pytest.mark.asyncio
async def test_link_to_existing_conflict_maps_to_409_no_trigger(monkeypatch):
    """Losing the race on the import insert => 409, feedback NOT triggered."""
    trigger_calls = []

    class _Job:
        async def trigger_feedback_processing(self, cr_id, skip_prereq_check=False):
            trigger_calls.append((cr_id, skip_prereq_check))
            return {"status": "processing"}

    monkeypatch.setattr(us, "get_feedback_job_service", lambda: _Job(), raising=False)

    fake = _FakeSupabase()
    fake.raise_on[("untracked_interview_imports", "insert")] = _unique_violation()

    with pytest.raises(us.UntrackedMutationError) as exc_info:
        await us.link_to_existing(
            fake,
            org_id=ORG_ID,
            source_candidate_round_id=SOURCE_CR_ID,
            target_requisition_id=TARGET_REQ_ID,
            target_round_id=TARGET_ROUND_ID,
            mode="new_candidate",
            imported_by_user_id="user-1",
        )

    assert exc_info.value.status_code == 409
    # Feedback must NOT be triggered on the losing path.
    assert trigger_calls == []
    # The import insert was attempted exactly once.
    assert len(_writes_of(fake, "untracked_interview_imports", "insert")) == 1
    # Any candidate_round the loser created must NOT survive: it is cancelled
    # (status update to 'cancelled') so no duplicate active round remains.
    cr_updates = _writes_of(fake, "candidate_rounds", "update")
    assert any(
        str(w[2].get("status")) == "cancelled" for w in cr_updates
    ), f"loser must cancel its candidate_round; updates={cr_updates}"


@pytest.mark.asyncio
async def test_mark_not_interview_conflict_maps_to_409(monkeypatch):
    """Losing the race on the dismiss insert => 409 (no duplicate dismiss row)."""
    fake = _FakeSupabase()
    fake.raise_on[("untracked_interview_imports", "insert")] = _unique_violation()

    with pytest.raises(us.UntrackedMutationError) as exc_info:
        await us.mark_not_interview(
            fake,
            org_id=ORG_ID,
            source_candidate_round_id=SOURCE_CR_ID,
            actor_user_id="user-1",
        )

    assert exc_info.value.status_code == 409
    # Exactly one insert attempt; the unique index rejected the duplicate.
    assert len(_writes_of(fake, "untracked_interview_imports", "insert")) == 1


@pytest.mark.asyncio
async def test_link_to_existing_happy_path_no_auto_trigger(monkeypatch):
    """No conflict: round created, import row written, and NO auto-trigger.

    Associate no longer fires the Lambda — the recruiter chooses Send-feedback-
    request or Process-transcript with the returned candidate_round id.
    """
    trigger_calls = []

    class _Job:
        async def trigger_feedback_processing(self, cr_id, skip_prereq_check=False):
            trigger_calls.append((cr_id, skip_prereq_check))
            return {"status": "processing"}

    monkeypatch.setattr(us, "get_feedback_job_service", lambda: _Job(), raising=False)

    fake = _FakeSupabase()
    result = await us.link_to_existing(
        fake,
        org_id=ORG_ID,
        source_candidate_round_id=SOURCE_CR_ID,
        target_requisition_id=TARGET_REQ_ID,
        target_round_id=TARGET_ROUND_ID,
        mode="new_candidate",
        imported_by_user_id="user-1",
    )

    assert result["target_candidate_round_id"] == NEW_TARGET_CR_ID
    assert result["candidate_created"] is True
    # Associate must NOT auto-process.
    assert trigger_calls == []
    # One import row inserted; no cancellation of the round.
    assert len(_writes_of(fake, "untracked_interview_imports", "insert")) == 1
    assert not any(
        str(w[2].get("status")) == "cancelled"
        for w in _writes_of(fake, "candidate_rounds", "update")
    )
