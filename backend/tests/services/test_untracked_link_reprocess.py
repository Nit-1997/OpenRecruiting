import pytest
import app.api.v2.services.untracked_service as us


# --- Integration-level test for the B3 guarantee -----------------------------
#
# The unit test above only proves the helper forwards skip_prereq_check. The
# B3 blocker is specifically that a *failing* feedback trigger must NOT break
# an already-committed merge. To exercise that genuinely we have to drive
# link_to_existing() end-to-end through its DB calls while the trigger raises.
#
# link_to_existing() talks to the DB exclusively through the `supabase`
# argument's fluent builder (`.table(name).select()...execute_async()`), so we
# inject a small table-routed fake instead of standing up respx + a real
# supabase client. The fake is a faithful recorder, not theater: every
# select/insert the function makes is routed by table name and returns the
# canned row the real code path would see, so the function runs its full
# happy path right up to (and through) the trigger's except block.

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
    """Records the operation/table, ignores filter chaining, and returns the
    canned response queued for (table, op) on execute_async()."""

    def __init__(self, fake, table):
        self._fake = fake
        self._table = table
        self._op = "select"

    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        # Record every insert payload by table so tests can assert the exact
        # columns written (the DB's NOT NULL constraints are not enforced by
        # this fake, so a regression that drops a required column is otherwise
        # invisible — that is exactly how the missing organization_id /
        # source_generic_candidate_id 500 shipped).
        self._fake.inserts.setdefault(self._table, []).append(payload)
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        # Recorded so the upsert test can assert the existing round was attached
        # in place (status/source_type/origin) instead of a duplicate insert.
        self._fake.updates.setdefault(self._table, []).append(payload)
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

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    async def execute_async(self):
        if self._op == "insert":
            # Simulate a tracker-insert failure (e.g. the import_status check
            # constraint) to exercise the self-healing rollback.
            if (
                self._table == "untracked_interview_imports"
                and self._fake.fail_imports_insert
            ):
                raise RuntimeError("imports insert boom")
            # Echo the inserted payload, stamped with the id the real DB would
            # assign, so the caller's _first(...) reads a usable row.
            row = dict(self._payload)
            row.setdefault("id", self._fake.insert_ids.get(self._table))
            return _FakeResponse([row])
        if self._op == "update":
            return _FakeResponse([dict(self._payload)])
        queue = self._fake.selects.get(self._table, [])
        data = queue.pop(0) if queue else []
        return _FakeResponse(data)


class _FakeSupabase:
    """Table-routed fake driving link_to_existing end-to-end.

    Two link shapes are exercised:
      - new_candidate (default): target candidate is created, has no round for
        the target round, so a candidate_round is INSERTED.
      - merge_existing (`merge_candidate` + `existing_target_round` set): the
        candidate already holds a round, so the interview is attached by UPDATE.
    """

    def __init__(
        self, *, merge_candidate=None, existing_target_round=None,
        fail_imports_insert=False,
    ):
        self.fail_imports_insert = fail_imports_insert
        # candidate_rounds: [_load_source_round, _existing_target_round].
        # candidates: [_load_candidate(source), email-lookup OR merge cand_check].
        second_candidates = [merge_candidate] if merge_candidate else []
        second_candidate_rounds = (
            [existing_target_round] if existing_target_round else []
        )
        self.selects = {
            "candidate_rounds": [
                # _load_source_round: must be source_type=untracked_generic
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
                # _existing_target_round: empty => insert, a row => update-in-place
                second_candidate_rounds,
            ],
            "candidates": [
                # _load_candidate: source candidate
                [{
                    "id": SOURCE_CAND_ID,
                    "requisition_id": SOURCE_REQ_ID,
                    "name": "Jane",
                    "email": "jane@test.com",
                    "phone": None,
                    "resume_url": None,
                }],
                # new_candidate: email lookup -> none, forces insert.
                # merge_existing: cand_check -> the candidate in the target req.
                second_candidates,
            ],
            "requisitions": [
                # _assert_source_in_org: system template in org
                [{
                    "id": SOURCE_REQ_ID,
                    "organization_id": ORG_ID,
                    "is_system_template": True,
                }],
                # _load_target_round req check: NOT system template, in org
                [{
                    "id": TARGET_REQ_ID,
                    "organization_id": ORG_ID,
                    "is_system_template": False,
                }],
            ],
            "untracked_interview_imports": [
                # _imports_for_source: no prior attempts
                [],
            ],
            "rounds": [
                # _load_target_round: the resolved target round
                [{
                    "id": TARGET_ROUND_ID,
                    "requisition_id": TARGET_REQ_ID,
                    "round_number": 1,
                }],
            ],
            "transcripts": [
                # _copy_interview_transcript: source interview transcript (has segments)
                [{
                    "segments": [{"speaker": "A", "text": "hi"}],
                    "full_text": "hi",
                    "raw_transcript_url": "https://t",
                    "word_count": 1,
                    "duration_seconds": 60,
                    "language": "en",
                    "provider": "recall",
                    "recall_transcript_id": "rt-1",
                    "participant_metadata": {},
                }],
                # target has no transcript yet -> insert
                [],
            ],
        }
        # Captured insert/update payloads, keyed by table (populated by _FakeQuery).
        self.inserts = {}
        self.updates = {}
        # Ids assigned to inserted rows, keyed by table.
        self.insert_ids = {
            "candidates": NEW_CAND_ID,
            "candidate_rounds": NEW_TARGET_CR_ID,
            "untracked_interview_imports": "import-1",
        }

    def table(self, name):
        return _FakeQuery(self, name)


@pytest.mark.asyncio
async def test_link_to_existing_no_auto_trigger_and_writes_interviewer(monkeypatch):
    """Associate does NOT auto-process (recruiter chooses) and writes the
    interviewer onto the target round.

    Processing the interview transcript alone yields only a thin rating, so the
    link no longer fires the Lambda — the recruiter picks "Send feedback request"
    or "Process transcript" with the returned candidate_round id.
    """
    trigger_calls = []

    class _Job:
        async def trigger_feedback_processing(self, cr_id, skip_prereq_check=False):
            trigger_calls.append((cr_id, skip_prereq_check))
            raise RuntimeError("should not be called")

    # untracked_service no longer imports get_feedback_job_service (no auto-trigger
    # on associate); raising=False keeps this trigger guard without requiring the
    # attribute to exist on the module.
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
        interviewer_email="iv@target.com",
        interviewer_name="Ivy Interviewer",
    )

    # Merge succeeded.
    assert result["target_candidate_round_id"] == NEW_TARGET_CR_ID
    assert result["target_requisition_id"] == TARGET_REQ_ID
    assert result["target_round_id"] == TARGET_ROUND_ID
    assert result["candidate_created"] is True

    # No auto-trigger — the Lambda is never invoked on associate.
    assert trigger_calls == []

    # The recruiter-supplied interviewer is written onto the target round.
    cr_payload = fake.inserts["candidate_rounds"][0]
    assert cr_payload["interviewer_email"] == "iv@target.com"
    assert cr_payload["interviewer_name"] == "Ivy Interviewer"

    # Regression guard: the untracked_interview_imports insert MUST carry every
    # NOT NULL column (migration 66). The v2 port dropped organization_id and
    # source_generic_candidate_id, so every real link 500'd on a not-null
    # violation while this fake (which doesn't enforce constraints) stayed green.
    imp_payload = fake.inserts["untracked_interview_imports"][0]
    for required_col in (
        "organization_id",
        "source_generic_candidate_id",
        "source_generic_candidate_round_id",
        "target_requisition_id",
        "target_round_id",
        "target_candidate_id",
        "target_candidate_round_id",
        "import_status",
    ):
        assert imp_payload.get(required_col), f"imports insert missing {required_col}"
    assert imp_payload["organization_id"] == ORG_ID
    assert imp_payload["source_generic_candidate_id"] == SOURCE_CAND_ID
    # import_status must satisfy untracked_interview_imports_import_status_check;
    # "imported" is NOT a valid value and 400'd every link.
    assert imp_payload["import_status"] in {
        "copied",
        "copied_pending_scorecard",
        "reprocessed",
        "reprocess_failed",
        "failed",
    }

    # The interview transcript is copied onto the target round so the feedback
    # Lambda (which reads transcripts by candidate_round_id) can score it. Without
    # this the merged round has no media and feedback produces nothing.
    tx_payload = fake.inserts["transcripts"][0]
    assert tx_payload["candidate_round_id"] == NEW_TARGET_CR_ID
    assert tx_payload["segments"]  # interview segments carried over
    # feedback_transcript is NOT copied — this is the interview, not feedback.
    assert "feedback_transcript" not in tx_payload


@pytest.mark.asyncio
async def test_link_to_existing_attaches_to_existing_round(monkeypatch):
    """Merge into an existing candidate attaches the interview to that
    candidate's EXISTING round (UPDATE) instead of inserting a duplicate.

    A pipeline candidate already holds a round per shared round, and
    idx_candidate_rounds_unique_non_generic (candidate_id, round_id) forbids a
    second — so the old blind insert 409'd every merge into an existing
    candidate. This proves the upsert path.
    """
    trigger_calls = []

    class _Job:
        async def trigger_feedback_processing(self, cr_id, skip_prereq_check=False):
            trigger_calls.append((cr_id, skip_prereq_check))
            return {"status": "processing"}

    # untracked_service no longer imports get_feedback_job_service (no auto-trigger
    # on associate); raising=False keeps this trigger guard without requiring the
    # attribute to exist on the module.
    monkeypatch.setattr(us, "get_feedback_job_service", lambda: _Job(), raising=False)

    existing_cr_id = "existing-cr-9"
    merge_cand_id = "merge-cand-9"
    fake = _FakeSupabase(
        merge_candidate={"id": merge_cand_id, "requisition_id": TARGET_REQ_ID},
        existing_target_round={
            "id": existing_cr_id,
            "status": "pending",
            "source_type": "standard",
        },
    )

    result = await us.link_to_existing(
        fake,
        org_id=ORG_ID,
        source_candidate_round_id=SOURCE_CR_ID,
        target_requisition_id=TARGET_REQ_ID,
        target_round_id=TARGET_ROUND_ID,
        mode="merge_existing",
        target_candidate_id=merge_cand_id,
        imported_by_user_id="user-1",
    )

    # Attached to the candidate's existing round — NO duplicate candidate_round insert.
    assert "candidate_rounds" not in fake.inserts
    assert result["target_candidate_round_id"] == existing_cr_id
    assert result["candidate_created"] is False

    # The existing round was updated in place with the captured interview.
    cr_update = fake.updates["candidate_rounds"][0]
    assert cr_update["status"] == "completed"
    assert cr_update["source_type"] == "untracked_copy"
    assert cr_update["origin_candidate_round_id"] == SOURCE_CR_ID

    # Import tracker points at the existing round; no auto-trigger on associate.
    imp = fake.inserts["untracked_interview_imports"][0]
    assert imp["target_candidate_round_id"] == existing_cr_id
    assert trigger_calls == []

    # Prior round snapshotted onto the import so undo can restore the scorecard.
    snap = imp["prior_round_snapshot"]
    assert snap is not None
    assert snap["round"]["status"] == "pending"
    assert snap["round"]["source_type"] == "standard"
    assert "feedback" in snap


@pytest.mark.asyncio
async def test_undo_link_calls_rpc():
    """undo_link delegates to the atomic undo RPC and returns its result."""
    calls = []

    class _Fake:
        async def rpc(self, fn, params):
            calls.append((fn, params))
            return _FakeResponse(
                {"untracked_id": params["p_source_cr_id"], "restored_prior_scorecard": True}
            )

    result = await us.undo_link(_Fake(), org_id="org-1", source_candidate_round_id="src-1")
    assert calls == [
        ("undo_untracked_link", {"p_org_id": "org-1", "p_source_cr_id": "src-1"})
    ]
    assert result["restored_prior_scorecard"] is True


@pytest.mark.asyncio
async def test_undo_link_404_when_no_active():
    """The RPC's 'no active link' raise maps to a clean 404."""

    class _Fake:
        async def rpc(self, fn, params):
            raise RuntimeError("no active untracked link to undo")

    with pytest.raises(us.UntrackedMutationError) as excinfo:
        await us.undo_link(_Fake(), org_id="org-1", source_candidate_round_id="src-1")
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_link_to_existing_restores_round_when_tracker_insert_fails(monkeypatch):
    """Self-healing: a tracker-insert failure AFTER the round was updated in
    place rolls the round back to its prior state — never left half-merged.

    This is the corruption mechanism behind the not-null and check-constraint
    regressions: the update committed, the tracker insert failed, and a real
    pipeline round was left as a phantom completed untracked-copy.
    """

    class _Job:
        async def trigger_feedback_processing(self, cr_id, skip_prereq_check=False):
            return {"status": "processing"}

    # untracked_service no longer imports get_feedback_job_service (no auto-trigger
    # on associate); raising=False keeps this trigger guard without requiring the
    # attribute to exist on the module.
    monkeypatch.setattr(us, "get_feedback_job_service", lambda: _Job(), raising=False)

    existing_cr_id = "existing-cr-restore"
    merge_cand_id = "merge-cand-restore"
    fake = _FakeSupabase(
        merge_candidate={"id": merge_cand_id, "requisition_id": TARGET_REQ_ID},
        existing_target_round={
            "id": existing_cr_id,
            "status": "scheduled",
            "source_type": "standard",
            "origin_candidate_round_id": None,
            "origin_detection_id": None,
            "scheduled_at": "2026-05-19T20:00:00+00:00",
            "completed_at": None,
            "interviewer_email": "priya-iv@test.com",
            "meeting_url": None,
            "recording_url": None,
            "transcript_url": None,
        },
        fail_imports_insert=True,
    )

    with pytest.raises(RuntimeError):
        await us.link_to_existing(
            fake,
            org_id=ORG_ID,
            source_candidate_round_id=SOURCE_CR_ID,
            target_requisition_id=TARGET_REQ_ID,
            target_round_id=TARGET_ROUND_ID,
            mode="merge_existing",
            target_candidate_id=merge_cand_id,
            imported_by_user_id="user-1",
        )

    # Two candidate_rounds updates: the link in place, then the rollback.
    updates = fake.updates["candidate_rounds"]
    assert len(updates) == 2
    restore = updates[-1]
    assert restore["status"] == "scheduled"
    assert restore["source_type"] == "standard"
    assert restore["origin_candidate_round_id"] is None
    assert restore["interviewer_email"] == "priya-iv@test.com"
