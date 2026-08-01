"""BE-S5: concurrency-race remediation for the legacy import path.

`UntrackedImportService.import_untracked_interview` previously created the
target candidate_round AND triggered the feedback Lambda BEFORE inserting the
unique-constrained audit row. Under a same-target double-submit, the loser
therefore fired feedback and created an orphan round before hitting 23505. The
fix claims the audit row (under uq_import_source_target) immediately after
creating the round and BEFORE triggering feedback, so a losing request:
  - never triggers feedback, and
  - has its orphan round cancelled,
and still surfaces a clean 409.

The fake supabase is a table-routed recorder; a chosen (table, op) insert can
raise PostgrestError(code="23505") to simulate losing the race.
"""

import pytest

import app.services.untracked_import_service as ims
from app.services.supabase import PostgrestError


ORG_ID = "org-1"
SOURCE_CR_ID = "src-cr-1"
SOURCE_CAND_ID = "src-cand-1"
SOURCE_REQ_ID = "src-req-1"
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

    def upsert(self, payload, **_k):
        self._op = "upsert"
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
        if self._op in ("insert", "update", "upsert"):
            self._fake.writes.append((self._table, self._op, self._payload))
            if key in self._fake.raise_on:
                raise self._fake.raise_on[key]
            row = dict(self._payload)
            row.setdefault("id", self._fake.insert_ids.get(self._table))
            return _FakeResponse([row])
        queue = self._fake.selects.get(self._table, [])
        data = queue.pop(0) if queue else []
        return _FakeResponse(data)

    async def count_async(self):
        return self._fake.counts.get(self._table, 0)


class _FakeSupabase:
    def __init__(self):
        self.selects = {
            "candidate_rounds": [
                # _get_source_round (has both recording+transcript so media
                # resolves without a recall_bots lookup)
                [{
                    "id": SOURCE_CR_ID,
                    "candidate_id": SOURCE_CAND_ID,
                    "round_id": "src-round-1",
                    "source_type": "untracked_generic",
                    "origin_detection_id": "det-1",
                    "scheduled_at": None,
                    "completed_at": None,
                    "interviewer_email": "iv@test.com",
                    "meeting_url": "https://m",
                    "scorecard_transcript": None,
                    "transcript_url": "https://t",
                    "recording_url": "https://r",
                    "processing_status": None,
                    "scorecard_status": None,
                    "summary": None,
                    "rating": None,
                    "question_summaries": None,
                    "outcome": None,
                    "outcome_notes": None,
                }],
                # conflict check before insert: no existing target round
                [],
            ],
            "candidates": [
                # _get_candidate (source)
                [{
                    "id": SOURCE_CAND_ID,
                    "requisition_id": SOURCE_REQ_ID,
                    "name": "Jane",
                    "email": "jane@test.com",
                }],
                # _resolve_target_candidate: by source_email -> none
                [],
                # _resolve_target_candidate: by target_email -> none (forces add)
                [],
            ],
            "requisitions": [
                # _get_requisition(source) -> system template in org
                [{
                    "id": SOURCE_REQ_ID,
                    "organization_id": ORG_ID,
                    "is_system_template": True,
                    "role_title": "Untracked",
                }],
                # _get_target_requisition -> not system template, in org
                [{
                    "id": TARGET_REQ_ID,
                    "organization_id": ORG_ID,
                    "is_system_template": False,
                    "role_title": "Backend Eng",
                }],
            ],
            "rounds": [
                # target round lookup
                [{"id": TARGET_ROUND_ID}],
            ],
            "untracked_interview_imports": [
                # existing_import (by source round) -> none
                [],
                # existing_by_detection -> none
                [],
            ],
            "transcripts": [
                # _copy_transcript_record select -> none (no copy)
                [],
            ],
        }
        self.counts = {"feedback_questions": 1}  # has questions -> would trigger
        self.insert_ids = {
            "candidates": NEW_CAND_ID,
            "candidate_rounds": NEW_TARGET_CR_ID,
            "untracked_interview_imports": "import-1",
        }
        self.raise_on: dict[tuple[str, str], Exception] = {}
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


def _patch_candidate_service(monkeypatch):
    class _CandSvc:
        async def add_candidate(self, **_k):
            return {"candidate": {"id": NEW_CAND_ID}}

    monkeypatch.setattr(ims, "get_candidate_service", lambda: _CandSvc())


@pytest.mark.asyncio
async def test_import_conflict_409_no_trigger_round_cancelled(monkeypatch):
    """Audit-row 23505 => 409; feedback NOT triggered; orphan round cancelled."""
    trigger_calls = []

    class _Job:
        async def trigger_feedback_processing(self, cr_id, skip_prereq_check=False):
            trigger_calls.append(cr_id)
            return {"status": "accepted"}

    monkeypatch.setattr(ims, "get_feedback_job_service", lambda: _Job())
    _patch_candidate_service(monkeypatch)

    fake = _FakeSupabase()
    fake.raise_on[("untracked_interview_imports", "insert")] = _unique_violation()

    svc = ims.UntrackedImportService(fake)
    with pytest.raises(ims.UntrackedImportError) as exc_info:
        await svc.import_untracked_interview(
            req_id=TARGET_REQ_ID,
            source_candidate_round_id=SOURCE_CR_ID,
            target_round_id=TARGET_ROUND_ID,
            org_id=ORG_ID,
            imported_by_user_id="user-1",
        )

    assert exc_info.value.status_code == 409
    # Feedback must NOT have been triggered on the losing path.
    assert trigger_calls == []
    # The orphan candidate_round this request created is cancelled.
    cr_updates = _writes_of(fake, "candidate_rounds", "update")
    assert any(str(w[2].get("status")) == "cancelled" for w in cr_updates), (
        f"loser must cancel its candidate_round; updates={cr_updates}"
    )


@pytest.mark.asyncio
async def test_existing_round_conflict_409_does_not_supersede(monkeypatch):
    """EXISTING_ROUND_CONFLICT 409 (target candidate already holds the round,
    override=false) must NOT supersede the source's prior active attempt — the
    supersede is deferred until after the conflict check, so an abandoned override
    prompt never leaves the source with zero active imports."""
    _patch_candidate_service(monkeypatch)

    fake = _FakeSupabase()
    # Target candidate already holds the target round -> conflict_row present.
    fake.selects["candidate_rounds"][1] = [{
        "id": "existing-tgt-cr", "status": "completed", "source_type": "manual",
        "origin_candidate_round_id": None, "recording_url": None,
        "transcript_url": None, "scorecard_transcript": None, "completed_at": None,
    }]

    svc = ims.UntrackedImportService(fake)

    # Force an EXISTING target candidate (candidate_created=False) so the conflict
    # resolves to the 409 branch, not the reuse branch.
    async def _existing_candidate(**_k):
        return ("existing-cand", False)
    monkeypatch.setattr(svc, "_resolve_target_candidate", _existing_candidate)

    # Spy: the supersede must never run on the 409 path.
    superseded_calls = []
    async def _spy_supersede(**kwargs):
        superseded_calls.append(kwargs)
    monkeypatch.setattr(svc, "_supersede_prior_active_import", _spy_supersede)

    with pytest.raises(ims.UntrackedImportError) as exc_info:
        await svc.import_untracked_interview(
            req_id=TARGET_REQ_ID,
            source_candidate_round_id=SOURCE_CR_ID,
            target_round_id=TARGET_ROUND_ID,
            org_id=ORG_ID,
            imported_by_user_id="user-1",
        )

    assert exc_info.value.status_code == 409
    assert superseded_calls == [], "supersede must be deferred past the conflict check"
    # No new round/import created on the conflict path.
    assert _writes_of(fake, "untracked_interview_imports", "insert") == []


@pytest.mark.asyncio
async def test_import_happy_path_triggers_once(monkeypatch):
    """No conflict: audit row claimed, then feedback triggered exactly once."""
    trigger_calls = []

    class _Job:
        async def trigger_feedback_processing(self, cr_id, skip_prereq_check=False):
            trigger_calls.append(cr_id)
            return {"status": "accepted"}

    monkeypatch.setattr(ims, "get_feedback_job_service", lambda: _Job())
    _patch_candidate_service(monkeypatch)

    fake = _FakeSupabase()
    svc = ims.UntrackedImportService(fake)
    result = await svc.import_untracked_interview(
        req_id=TARGET_REQ_ID,
        source_candidate_round_id=SOURCE_CR_ID,
        target_round_id=TARGET_ROUND_ID,
        org_id=ORG_ID,
        imported_by_user_id="user-1",
    )

    assert result["target_candidate_round_id"] == NEW_TARGET_CR_ID
    assert result["import_status"] == "reprocessed"
    # Exactly one trigger, with the new round id.
    assert trigger_calls == [NEW_TARGET_CR_ID]
    # Exactly one audit insert; no round cancellation.
    assert len(_writes_of(fake, "untracked_interview_imports", "insert")) == 1
    assert not any(
        str(w[2].get("status")) == "cancelled"
        for w in _writes_of(fake, "candidate_rounds", "update")
    )
