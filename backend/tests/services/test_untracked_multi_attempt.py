"""UNTRACKED-MA: flexible multi-attempt association model.

An untracked interview can be (re)associated to candidate-rounds over time:
reassigning to a different candidate/round supersedes the prior attempt (its
round is cancelled but its feedback is KEPT/restorable), and the latest is
honored. Reassigning BACK to a prior target reactivates the superseded attempt
instead of inserting (avoiding the uq_import_source_target collision). Linking
to the same active target is an idempotent 409.

These tests cover the v2 link path (untracked_service.link_to_existing). The
legacy import path (untracked_import_service.import_untracked_interview) is
covered in test_untracked_import_service.py.

The fake supabase is the same table-routed FIFO recorder used by the other
untracked tests, extended with a writes log + per-(table,op) raise hook.
"""

import pytest

import app.api.v2.services.untracked_service as us
from app.services.supabase import PostgrestError


ORG_ID = "org-1"
SOURCE_CR_ID = "src-cr-1"
SOURCE_CAND_ID = "src-cand-1"
SOURCE_REQ_ID = "src-req-1"  # the generic/system requisition

REQ_A = "req-a"
ROUND_A = "round-a"
CR_A = "cr-a"  # the candidate_round created for the A attempt

REQ_B = "req-b"
ROUND_B = "round-b"
CR_B = "cr-b"  # the candidate_round created for the B attempt
NEW_CAND_ID = "new-cand-1"


class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
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
            return _Resp([row])
        queue = self._fake.selects.get(self._table, [])
        data = queue.pop(0) if queue else []
        return _Resp(data)


class _FakeSb:
    def __init__(self, *, imports_for_source):
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
                [{"id": SOURCE_REQ_ID, "organization_id": ORG_ID, "is_system_template": True}],
                # target req (not system) — reused for whichever req under test
                [{"id": REQ_B, "organization_id": ORG_ID, "is_system_template": False}],
            ],
            "untracked_interview_imports": [imports_for_source],
            "rounds": [
                [{"id": ROUND_B, "requisition_id": REQ_B, "round_number": 1}],
            ],
            "transcripts": [
                # _copy_interview_transcript: source interview transcript, then the
                # target's existing-row check (none -> insert).
                [{"segments": [{"speaker": "A", "text": "hi"}], "full_text": "hi",
                  "raw_transcript_url": None, "word_count": 1, "duration_seconds": 60,
                  "language": "en", "provider": "recall", "recall_transcript_id": "rt",
                  "participant_metadata": {}}],
                [],
            ],
        }
        self.insert_ids = {
            "candidates": NEW_CAND_ID,
            "candidate_rounds": CR_B,
            "untracked_interview_imports": "import-new",
        }
        self.raise_on: dict[tuple, Exception] = {}
        self.writes: list[tuple] = []

    def table(self, name):
        return _Q(self, name)

    def writes_to(self, table, op):
        return [w for w in self.writes if w[0] == table and w[1] == op]


def _patch_feedback(monkeypatch):
    """Record any feedback-Lambda trigger. The link/reactivate paths no longer
    auto-process (spec locked decision 1), so `calls` must stay empty — this
    stays as a regression guard. raising=False because untracked_service no
    longer imports get_feedback_job_service at all."""
    calls = []

    class _Job:
        async def trigger_feedback_processing(self, cr_id, skip_prereq_check=False):
            calls.append((cr_id, skip_prereq_check))
            return {"status": "processing"}

    monkeypatch.setattr(us, "get_feedback_job_service", lambda: _Job(), raising=False)
    return calls


def _set_target(fake, *, req_id, round_id):
    """Point the fake's target requisition + round at the given ids."""
    fake.selects["requisitions"][1] = [
        {"id": req_id, "organization_id": ORG_ID, "is_system_template": False}
    ]
    fake.selects["rounds"][0] = [
        {"id": round_id, "requisition_id": req_id, "round_number": 1}
    ]


@pytest.mark.asyncio
async def test_reassign_new_target_supersedes_prior_and_cancels_round(monkeypatch):
    """A->B reassign: B becomes active (new round + import), A's import is
    superseded, A's round is cancelled, A's feedback is KEPT, and associate
    does NOT auto-process."""
    calls = _patch_feedback(monkeypatch)
    # Source currently has one ACTIVE attempt on A.
    fake = _FakeSb(imports_for_source=[{
        "id": "imp-a", "target_requisition_id": REQ_A, "target_round_id": ROUND_A,
        "target_candidate_id": "cand-a", "target_candidate_round_id": CR_A,
        "import_status": "imported", "superseded_at": None,
        "created_at": "2026-01-01T00:00:00Z",
    }])
    _set_target(fake, req_id=REQ_B, round_id=ROUND_B)

    result = await us.link_to_existing(
        fake,
        org_id=ORG_ID,
        source_candidate_round_id=SOURCE_CR_ID,
        target_requisition_id=REQ_B,
        target_round_id=ROUND_B,
        mode="new_candidate",
        imported_by_user_id="user-1",
    )

    assert result["target_candidate_round_id"] == CR_B
    assert result["target_requisition_id"] == REQ_B
    # Associate (incl. reassign to a NEW target) does not auto-process.
    assert calls == []
    # A's import was superseded (superseded_at stamped on imp-a).
    imp_updates = fake.writes_to("untracked_interview_imports", "update")
    assert any(w[2].get("superseded_at") for w in imp_updates), (
        f"prior active import must be superseded; updates={imp_updates}")
    # A's round (CR_A) cancelled; no feedback deleted anywhere.
    cr_cancels = [w for w in fake.writes_to("candidate_rounds", "update")
                  if str(w[2].get("status")) == "cancelled"]
    assert cr_cancels, "A's prior round must be cancelled"
    assert not fake.writes_to("candidate_feedback", "delete")
    # Exactly one new import row inserted (the B attempt).
    assert len(fake.writes_to("untracked_interview_imports", "insert")) == 1


@pytest.mark.asyncio
async def test_reassign_back_reactivates_superseded_import(monkeypatch):
    """B->A reassign-back where A was previously used (now superseded):
    reactivate A's import (clear superseded_at), restore its round, NO new
    insert (so no uq_import_source_target violation), and supersede the current
    active B attempt."""
    calls = _patch_feedback(monkeypatch)
    # Source has: superseded A attempt + active B attempt (newest first).
    fake = _FakeSb(imports_for_source=[
        {
            "id": "imp-b", "target_requisition_id": REQ_B, "target_round_id": ROUND_B,
            "target_candidate_id": "cand-b", "target_candidate_round_id": CR_B,
            "import_status": "imported", "superseded_at": None,
            "created_at": "2026-02-01T00:00:00Z",
        },
        {
            "id": "imp-a", "target_requisition_id": REQ_A, "target_round_id": ROUND_A,
            "target_candidate_id": "cand-a", "target_candidate_round_id": CR_A,
            "import_status": "imported", "superseded_at": "2026-02-01T00:00:00Z",
            "created_at": "2026-01-01T00:00:00Z",
        },
    ])
    _set_target(fake, req_id=REQ_A, round_id=ROUND_A)

    result = await us.link_to_existing(
        fake,
        org_id=ORG_ID,
        source_candidate_round_id=SOURCE_CR_ID,
        target_requisition_id=REQ_A,
        target_round_id=ROUND_A,
        mode="new_candidate",
        imported_by_user_id="user-1",
    )

    assert result["target_candidate_round_id"] == CR_A
    assert result["candidate_created"] is False
    # NO new import row inserted (reactivation, not insert) — avoids the
    # uq_import_source_target collision on the prior (source, A) target.
    assert fake.writes_to("untracked_interview_imports", "insert") == []
    # imp-a reactivated (superseded_at cleared to None).
    imp_updates = fake.writes_to("untracked_interview_imports", "update")
    assert any(
        w[2].get("superseded_at") is None and "superseded_at" in w[2]
        for w in imp_updates
    ), f"imp-a must be reactivated (superseded_at None); updates={imp_updates}"
    # imp-b (the other active attempt) superseded.
    assert any(w[2].get("superseded_at") for w in imp_updates), (
        "the other active attempt (imp-b) must be superseded")
    # A's round restored to completed; B's round cancelled.
    cr_updates = fake.writes_to("candidate_rounds", "update")
    assert any(str(w[2].get("status")) == "completed" for w in cr_updates), (
        "reactivated A round must be restored to completed")
    assert any(str(w[2].get("status")) == "cancelled" for w in cr_updates), (
        "the superseded B round must be cancelled")
    # Reactivate does NOT auto-process (matches the main link path / spec locked
    # decision 1): the recruiter chooses Process/Send-feedback next.
    assert calls == []
    # The interview transcript is RE-COPIED onto the restored round. A prior undo
    # deletes the target's copied transcript; without re-copy the reactivated round
    # is media-less and the recruiter's first Process/Send-feedback fails.
    tx_inserts = fake.writes_to("transcripts", "insert")
    assert tx_inserts, "reactivate must re-copy the interview transcript"
    assert tx_inserts[0][2].get("candidate_round_id") == CR_A
    assert tx_inserts[0][2].get("segments")


@pytest.mark.asyncio
async def test_link_same_active_target_is_idempotent(monkeypatch):
    """Linking to the SAME currently-active target again -> idempotent SUCCESS
    (returns the existing association), NOT a 409. The FE's Process/Send-feedback
    actions re-link before processing, so a 409 here blocked re-processing an
    already-associated interview. No new round, no new import, no feedback
    trigger; the interview transcript is re-copied so the round stays processable."""
    calls = _patch_feedback(monkeypatch)
    fake = _FakeSb(imports_for_source=[{
        "id": "imp-b", "target_requisition_id": REQ_B, "target_round_id": ROUND_B,
        "target_candidate_id": "cand-b", "target_candidate_round_id": CR_B,
        "import_status": "imported", "superseded_at": None,
        "created_at": "2026-02-01T00:00:00Z",
    }])
    _set_target(fake, req_id=REQ_B, round_id=ROUND_B)

    result = await us.link_to_existing(
        fake,
        org_id=ORG_ID,
        source_candidate_round_id=SOURCE_CR_ID,
        target_requisition_id=REQ_B,
        target_round_id=ROUND_B,
        mode="new_candidate",
        imported_by_user_id="user-1",
        interviewer_email="iv@test.com",
    )

    # Returns the existing association (so the caller can process/request feedback).
    assert result["target_candidate_round_id"] == CR_B
    assert result["candidate_created"] is False
    # No supersede, no new round, no new import, no auto-trigger.
    assert calls == []
    assert fake.writes_to("untracked_interview_imports", "insert") == []
    assert fake.writes_to("candidate_rounds", "insert") == []
    assert fake.writes_to("untracked_interview_imports", "update") == []
    # Transcript re-copied onto the existing round so it stays processable.
    tx_inserts = fake.writes_to("transcripts", "insert")
    assert tx_inserts and tx_inserts[0][2].get("candidate_round_id") == CR_B


@pytest.mark.asyncio
async def test_merge_existing_invalid_candidate_404_does_not_supersede(monkeypatch):
    """merge_existing to a candidate NOT in the target requisition -> 404, and the
    source's prior active attempt must NOT be superseded (the supersede is deferred
    until after the candidate-in-requisition check, so a failed request never
    retires the existing link without creating a replacement)."""
    calls = _patch_feedback(monkeypatch)
    fake = _FakeSb(imports_for_source=[{
        "id": "imp-a", "target_requisition_id": REQ_A, "target_round_id": ROUND_A,
        "target_candidate_id": "cand-a", "target_candidate_round_id": CR_A,
        "import_status": "imported", "superseded_at": None,
        "created_at": "2026-01-01T00:00:00Z",
    }])
    _set_target(fake, req_id=REQ_B, round_id=ROUND_B)
    # merge_existing candidate check (the 2nd candidates select) returns [] —
    # candidate not in the requisition. The default fake already supplies that.

    with pytest.raises(us.UntrackedMutationError) as ei:
        await us.link_to_existing(
            fake,
            org_id=ORG_ID,
            source_candidate_round_id=SOURCE_CR_ID,
            target_requisition_id=REQ_B,
            target_round_id=ROUND_B,
            mode="merge_existing",
            target_candidate_id="outsider-cand",
            imported_by_user_id="user-1",
        )

    assert ei.value.status_code == 404
    # The prior active attempt must remain intact: no supersede stamp, no cancel.
    imp_updates = fake.writes_to("untracked_interview_imports", "update")
    assert not any(w[2].get("superseded_at") for w in imp_updates), (
        f"prior active import must NOT be superseded on a failed merge; updates={imp_updates}")
    assert not [w for w in fake.writes_to("candidate_rounds", "update")
                if str(w[2].get("status")) == "cancelled"], "prior round must not be cancelled"
    assert calls == []


@pytest.mark.asyncio
async def test_concurrent_same_target_double_submit_409_via_uq(monkeypatch):
    """Two concurrent links to the same NEW target: the loser's import insert
    collides on uq_import_source_target (23505) -> 409, its orphan round is
    cancelled, and feedback is NOT fired."""
    calls = _patch_feedback(monkeypatch)
    # No prior attempts: this is a genuinely new target for both racers.
    fake = _FakeSb(imports_for_source=[])
    _set_target(fake, req_id=REQ_B, round_id=ROUND_B)
    fake.raise_on[("untracked_interview_imports", "insert")] = PostgrestError(
        message='duplicate key value violates unique constraint "uq_import_source_target"',
        code="23505",
    )

    with pytest.raises(us.UntrackedMutationError) as ei:
        await us.link_to_existing(
            fake,
            org_id=ORG_ID,
            source_candidate_round_id=SOURCE_CR_ID,
            target_requisition_id=REQ_B,
            target_round_id=ROUND_B,
            mode="new_candidate",
            imported_by_user_id="user-1",
        )

    assert ei.value.status_code == 409
    assert calls == []
    # Orphan round cancelled.
    assert any(
        str(w[2].get("status")) == "cancelled"
        for w in fake.writes_to("candidate_rounds", "update")
    )
    # Exactly one import insert attempt (it raised).
    assert len(fake.writes_to("untracked_interview_imports", "insert")) == 1
