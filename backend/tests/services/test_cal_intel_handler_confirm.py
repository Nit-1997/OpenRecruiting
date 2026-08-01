"""BE-T8 characterization tests for calendar_intelligence_handler._confirm.

Pins CURRENT behavior of the ~450-line confirmation effect-chain in
`_confirm`: candidate resolve/create, candidate_round upsert (existing reuse vs
fresh insert), the untracked-import (copy) path + its existing-round conflict
warning, multi-candidate disambiguation re-entry, bot link, the final CAS
success + CAS-conflict, and the compensation/rollback on a mid-step failure.

ALL effect boundaries are mocked: Supabase via a table-routed fake recorder
(reused shape from the BE-T2 handler test), the Recall service, the candidate
service, the feedback-Lambda trigger, the untracked-import service, Slack
message updates, and httpx. No production code is modified. Where a quirk is
found it is DOCUMENTED (CHARACTERIZED) and the test asserts CURRENT behavior.
"""

import json
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.services.calendar_intelligence_handler as h


# ===========================================================================
# Table-routed fake Supabase — same contract as the BE-T2 handler test.
#   - selects: table -> FIFO list of result-lists (one per select call)
#   - write_results: (table, op) -> FIFO list of result-lists controlling CAS
#   - raise_on: (table, op) -> exception to raise on that write
#   - default write (no override) echoes the payload back as a single row
# ===========================================================================


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

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def insert(self, payload):
        self._op = "insert"
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

    def in_(self, *_a, **_k):
        return self

    def is_(self, *_a, **_k):
        return self

    def is_null(self, *_a, **_k):
        return self

    def ilike(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def single(self, *_a, **_k):
        return self

    async def execute_async(self):
        key = (self._table, self._op)
        if self._op in ("insert", "update", "upsert"):
            self._fake.writes.append((self._table, self._op, self._payload))
            if key in self._fake.raise_on:
                raise self._fake.raise_on[key]
            if key in self._fake.write_results:
                queue = self._fake.write_results[key]
                data = queue.pop(0) if queue else []
                return _FakeResponse(data)
            row = dict(self._payload) if isinstance(self._payload, dict) else {}
            return _FakeResponse([row])
        queue = self._fake.selects.get(self._table, [])
        data = queue.pop(0) if queue else []
        return _FakeResponse(data)


class _FakeSupabase:
    def __init__(self, selects=None, write_results=None):
        self.selects = {k: list(v) for k, v in (selects or {}).items()}
        self.write_results = {k: list(v) for k, v in (write_results or {}).items()}
        self.raise_on = {}
        self.writes = []

    def table(self, name):
        return _FakeQuery(self, name)


# ===========================================================================
# Shared fixtures / builders
# ===========================================================================


PROFILE_ID = "prof-1"
ORG_ID = "org-1"
DETECTION_ID = "det-12345678"
REQ_ID = "r1"
ROUND_ID = "rd1"
CANDIDATE_ID = "cand-1"
CR_ID = "cr-1"


def _detection_row(status="awaiting_confirm", **overrides):
    row = {
        "id": DETECTION_ID,
        "profile_id": PROFILE_ID,
        "organization_id": ORG_ID,
        "detection_status": status,
        "event_title": "Jane Doe <> John Smith",
        "event_start": "2025-01-15T14:00:00+00:00",
        "meeting_platform": "zoom",
        "meeting_url": "https://zoom.us/j/1",
        "matched_requisition_id": REQ_ID,
        "matched_candidate_id": None,
        "matched_candidate_round_id": None,
        "external_attendees": [{"email": "jane@cand.com", "display_name": "Jane Doe"}],
        "internal_attendees": [
            {"email": "john.smith@acme.com", "display_name": "John Smith", "self": True}
        ],
        "detection_signals": {"_ui_state": {"current_step": "review", "role_title": "SWE"}},
        "detection_confidence": 0.9,
    }
    row.update(overrides)
    return row


def _round_row(**overrides):
    row = {
        "id": ROUND_ID,
        "name": "Technical",
        "requisition_id": REQ_ID,
        "round_number": 1,
        "default_interviewer_emails": ["john.smith@acme.com"],
        "duration_minutes": 45,
    }
    row.update(overrides)
    return row


def _action_payload(action_id="cal_intel_confirm", value=None):
    return {
        "actions": [{"action_id": action_id, "value": json.dumps(value or {"detection_id": DETECTION_ID, "round_id": ROUND_ID})}],
        "user": {"id": "slack-user-1"},
        "team": {"id": "T1"},
        "response_url": "https://hooks.slack.test/r",
        "channel": {"id": "C1"},
        "message": {"ts": "111.222"},
    }


@pytest.fixture
def captured_blocks(monkeypatch):
    captured = []

    async def _fake_update(payload, blocks):
        captured.append(blocks)

    monkeypatch.setattr(h, "_update_slack_message", _fake_update)
    return captured


@contextmanager
def _patched_externals(
    *,
    recall=None,
    candidate_service=None,
    feedback=None,
):
    """Patch the inner-imported external services that _confirm reaches.

    These are imported inside functions, so they must be patched at their
    source module, not on the handler module.
    """
    recall = recall or AsyncMock()
    recall.delete_bot = AsyncMock(return_value=True)
    recall.remove_bot_from_call = AsyncMock(return_value=True)
    recall.close = AsyncMock()

    cand_svc = candidate_service or AsyncMock()
    feedback_svc = feedback or AsyncMock()
    feedback_svc.trigger_feedback_processing = AsyncMock(return_value={})

    with patch("app.services.recall_service.get_recall_service", return_value=recall), \
         patch("app.services.recall_service.schedule_or_replace_recall_bot", new=AsyncMock()), \
         patch("app.services.candidate_service.get_candidate_service", return_value=cand_svc), \
         patch("app.services.feedback_job_service.get_feedback_job_service", return_value=feedback_svc):
        yield {"recall": recall, "candidate_service": cand_svc, "feedback": feedback_svc}


def _det_updates(fake):
    return [w for w in fake.writes if w[0] == "calendar_event_detections" and w[1] == "update"]


# ===========================================================================
# _confirm — guard rails
# ===========================================================================


async def test_confirm_missing_round_id_prompts(captured_blocks):
    await h._confirm(DETECTION_ID, None, _action_payload(value={"detection_id": DETECTION_ID}))
    assert "select a round first" in str(captured_blocks[-1])


async def test_confirm_already_confirmed_raises(captured_blocks):
    fake = _FakeSupabase(selects={"calendar_event_detections": [[_detection_row(status="confirmed")]]})
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.DetectionAlreadyProcessedError):
            await h._confirm(DETECTION_ID, ROUND_ID, _action_payload())


async def test_confirm_non_confirmable_status_raises(captured_blocks):
    # CHARACTERIZED: "detected" cannot reach "confirmed" in the transition
    # graph, so it is NOT in CONFIRMABLE_STATUSES (and not CONFIRM_LOCKED)
    # => the second guard rejects it. ("notified" IS confirmable.)
    fake = _FakeSupabase(selects={"calendar_event_detections": [[_detection_row(status="detected")]]})
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.DetectionAlreadyProcessedError):
            await h._confirm(DETECTION_ID, ROUND_ID, _action_payload())


async def test_confirm_lock_cas_conflict_raises(captured_blocks):
    # The very first CAS (status -> confirming) returns empty .data => stolen.
    fake = _FakeSupabase(
        selects={"calendar_event_detections": [[_detection_row(status="awaiting_confirm")]]},
        write_results={("calendar_event_detections", "update"): [[]]},
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.DetectionAlreadyProcessedError):
            await h._confirm(DETECTION_ID, ROUND_ID, _action_payload())


async def test_confirm_round_deleted_rolls_back_and_raises(captured_blocks):
    # confirming lock succeeds, then round lookup is empty => RoundDeletedError,
    # and the except-block rolls the detection status back to `current`.
    det = _detection_row(status="awaiting_confirm")
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[]],  # round lookup empty
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.RoundDeletedError):
            await h._confirm(DETECTION_ID, ROUND_ID, _action_payload())
    # Last detection update rolls status back to the pre-confirming value.
    ups = _det_updates(fake)
    assert ups[0][2]["detection_status"] == "confirming"
    assert ups[-1][2]["detection_status"] == "awaiting_confirm"


# ===========================================================================
# _confirm — fresh confirm, NEW candidate created + fresh CR inserted
# ===========================================================================


async def test_confirm_fresh_new_candidate_and_cr_insert(captured_blocks):
    det = _detection_row(status="awaiting_confirm")
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[_round_row()]],
            "user_connections": [[{"provider_email": "recruiter@acme.com"}]],
            "requisitions": [[{"created_by": PROFILE_ID}]],   # req_owner check
            "candidates": [[]],                                # no existing candidate
            "candidate_rounds": [[]],                          # no existing CR
            "recall_bots": [[{"id": "b1", "recall_bot_id": "rb1", "status": "joining",
                              "transcript_ready": False, "transcript_url": None}]],
        },
        write_results={("candidate_rounds", "insert"): [[{"id": CR_ID}]]},
    )
    cand_svc = AsyncMock()
    cand_svc.add_candidate = AsyncMock(return_value={"candidate": {"id": CANDIDATE_ID}})

    with patch.object(h, "get_supabase_admin_client", return_value=fake), \
         _patched_externals(candidate_service=cand_svc) as ext:
        await h._confirm(DETECTION_ID, ROUND_ID, _action_payload())

    # New candidate created via the candidate service.
    cand_svc.add_candidate.assert_awaited_once()
    # A fresh candidate_round was inserted as "scheduled".
    cr_inserts = [w for w in fake.writes if w[0] == "candidate_rounds" and w[1] == "insert"]
    assert cr_inserts
    assert cr_inserts[0][2]["status"] == "scheduled"
    assert cr_inserts[0][2]["meeting_url"] == "https://zoom.us/j/1"
    # The bot was linked to the new CR (its candidate_round_id set on recall_bots).
    bot_updates = [w for w in fake.writes if w[0] == "recall_bots" and w[1] == "update"]
    assert any("candidate_round_id" in w[2] for w in bot_updates)
    # Final CAS flips detection to confirmed + records candidate_was_created.
    ups = _det_updates(fake)
    assert ups[-1][2]["detection_status"] == "confirmed"
    assert ups[-1][2]["candidate_was_created"] is True
    assert ups[-1][2]["undo_expires_at"]
    # Confirmation card rendered.
    assert captured_blocks


# ===========================================================================
# _confirm — existing candidate reused, existing CR reused (not inserted)
# ===========================================================================


async def test_confirm_existing_candidate_and_cr_reuse(captured_blocks):
    det = _detection_row(status="awaiting_confirm")
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[_round_row()]],
            "user_connections": [[{"provider_email": "recruiter@acme.com"}]],
            "requisitions": [[{"created_by": PROFILE_ID}]],
            "candidates": [[{"id": CANDIDATE_ID}]],            # existing candidate
            "candidate_rounds": [[{"id": CR_ID, "status": "pending", "meeting_url": None,
                                   "scheduled_at": None, "interviewer_email": None}]],
            "recall_bots": [[{"id": "b1", "recall_bot_id": "rb1", "status": "created",
                              "transcript_ready": False, "transcript_url": None}]],
        }
    )
    cand_svc = AsyncMock()
    with patch.object(h, "get_supabase_admin_client", return_value=fake), \
         _patched_externals(candidate_service=cand_svc):
        await h._confirm(DETECTION_ID, ROUND_ID, _action_payload())

    # No new candidate created (existing reused).
    cand_svc.add_candidate.assert_not_awaited()
    # Existing CR updated to scheduled (no insert).
    cr_inserts = [w for w in fake.writes if w[0] == "candidate_rounds" and w[1] == "insert"]
    assert cr_inserts == []
    cr_updates = [w for w in fake.writes if w[0] == "candidate_rounds" and w[1] == "update"]
    assert cr_updates
    assert cr_updates[0][2]["status"] == "scheduled"
    ups = _det_updates(fake)
    assert ups[-1][2]["detection_status"] == "confirmed"
    # CHARACTERIZED: reusing an existing CR => candidate_was_created False.
    assert ups[-1][2]["candidate_was_created"] is False


async def test_confirm_existing_cr_in_progress_raises(captured_blocks):
    # CHARACTERIZED: an in_progress / completed existing CR is a hard stop.
    det = _detection_row(status="awaiting_confirm")
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[_round_row()]],
            "user_connections": [[{"provider_email": "recruiter@acme.com"}]],
            "requisitions": [[{"created_by": PROFILE_ID}]],
            "candidates": [[{"id": CANDIDATE_ID}]],
            "candidate_rounds": [[{"id": CR_ID, "status": "completed"}]],
            "recall_bots": [[]],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake), _patched_externals():
        with pytest.raises(h.CalendarIntelligenceError):
            await h._confirm(DETECTION_ID, ROUND_ID, _action_payload())
    # Rolled back to awaiting_confirm.
    ups = _det_updates(fake)
    assert ups[-1][2]["detection_status"] == "awaiting_confirm"


# ===========================================================================
# _confirm — multi-candidate disambiguation re-entry (no selection)
# ===========================================================================


async def test_confirm_multi_candidate_unselected_reenters_review(captured_blocks):
    det = _detection_row(status="awaiting_confirm")
    det["external_attendees"] = [
        {"email": "a@cand.com", "display_name": "A"},
        {"email": "b@cand.com", "display_name": "B"},
    ]
    # No selected_candidate_email in ui_state.
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[_round_row()]],
            "user_connections": [[{"provider_email": "recruiter@acme.com"}]],
            "requisitions": [[{"created_by": PROFILE_ID}], [{"role_title": "SWE"}]],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake), _patched_externals():
        await h._confirm(DETECTION_ID, ROUND_ID, _action_payload())

    # No candidate / CR ever written; detection rolled back to awaiting_confirm.
    assert [w for w in fake.writes if w[0] == "candidate_rounds"] == []
    ups = _det_updates(fake)
    assert ups[-1][2]["detection_status"] == "awaiting_confirm"
    # Re-rendered review with the validation prompt.
    assert "select the candidate" in str(captured_blocks[-1]).lower()


async def test_confirm_multi_candidate_with_selection_proceeds(captured_blocks):
    det = _detection_row(status="awaiting_confirm")
    det["external_attendees"] = [
        {"email": "a@cand.com", "display_name": "A"},
        {"email": "b@cand.com", "display_name": "B"},
    ]
    det["detection_signals"] = {
        "_ui_state": {"current_step": "review", "role_title": "SWE",
                      "selected_candidate_email": "a@cand.com"}
    }
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[_round_row()]],
            "user_connections": [[{"provider_email": "recruiter@acme.com"}]],
            "requisitions": [[{"created_by": PROFILE_ID}]],
            "candidates": [[{"id": CANDIDATE_ID}]],
            "candidate_rounds": [[]],
            "recall_bots": [[{"id": "b1", "recall_bot_id": "rb1", "status": "joining",
                              "transcript_ready": False, "transcript_url": None}]],
        },
        write_results={("candidate_rounds", "insert"): [[{"id": CR_ID}]]},
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake), _patched_externals():
        await h._confirm(DETECTION_ID, ROUND_ID, _action_payload())

    ups = _det_updates(fake)
    assert ups[-1][2]["detection_status"] == "confirmed"
    # Confirmed against candidate A only.
    cr_inserts = [w for w in fake.writes if w[0] == "candidate_rounds" and w[1] == "insert"]
    assert cr_inserts and cr_inserts[0][2]["candidate_id"] == CANDIDATE_ID


# ===========================================================================
# _confirm — bot link failure => BotDeploymentError + rollback
# ===========================================================================


async def test_confirm_bot_link_failure_rolls_back(captured_blocks):
    det = _detection_row(status="awaiting_confirm")
    # No bot rows and no meeting_url path will produce a link => returns False.
    # NB: _link_bot_to_candidate_round re-fetches the detection on the
    # no-active-bots branch, so two detection selects are queued.
    det["meeting_url"] = ""
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det], [det]],
            "rounds": [[_round_row()]],
            "user_connections": [[{"provider_email": "recruiter@acme.com"}]],
            "requisitions": [[{"created_by": PROFILE_ID}]],
            "candidates": [[{"id": CANDIDATE_ID}]],
            "candidate_rounds": [[]],                          # fresh insert
            "recall_bots": [[]],                               # no attachable bot
        },
        write_results={("candidate_rounds", "insert"): [[{"id": CR_ID}]]},
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake), _patched_externals():
        with pytest.raises(h.BotDeploymentError):
            await h._confirm(DETECTION_ID, ROUND_ID, _action_payload())

    # The freshly-created CR is compensated (cancelled) by the except-block.
    cr_updates = [w for w in fake.writes if w[0] == "candidate_rounds" and w[1] == "update"]
    assert any(w[2].get("status") == "cancelled" for w in cr_updates)
    ups = _det_updates(fake)
    assert ups[-1][2]["detection_status"] == "awaiting_confirm"


# ===========================================================================
# _confirm — final CAS conflict => rollback of created CR + raise
# ===========================================================================


async def test_confirm_final_cas_conflict_rolls_back(captured_blocks):
    det = _detection_row(status="awaiting_confirm")
    # First detection update (lock -> confirming) succeeds (default echo),
    # final CAS (confirming -> confirmed) returns empty .data => stolen.
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[_round_row()]],
            "user_connections": [[{"provider_email": "recruiter@acme.com"}]],
            "requisitions": [[{"created_by": PROFILE_ID}]],
            "candidates": [[{"id": CANDIDATE_ID}]],
            "candidate_rounds": [[]],
            "recall_bots": [[{"id": "b1", "recall_bot_id": "rb1", "status": "joining",
                              "transcript_ready": False, "transcript_url": None}]],
        },
        # 1st det update = lock (echo => non-empty), 2nd = final CAS (empty),
        # 3rd = rollback (echo).
        write_results={
            ("calendar_event_detections", "update"): [
                [{"detection_status": "confirming"}],  # lock OK
                [],                                     # final CAS miss
            ],
            ("candidate_rounds", "insert"): [[{"id": CR_ID}]],
        },
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake), _patched_externals():
        with pytest.raises(h.DetectionAlreadyProcessedError):
            await h._confirm(DETECTION_ID, ROUND_ID, _action_payload())
    # The fresh CR is compensated (cancelled) by the except-block.
    cr_updates = [w for w in fake.writes if w[0] == "candidate_rounds" and w[1] == "update"]
    assert any(w[2].get("status") == "cancelled" for w in cr_updates)


# ===========================================================================
# _confirm — bot link with transcript-ready bot triggers feedback once
# ===========================================================================


async def test_confirm_links_ready_transcript_triggers_feedback(captured_blocks):
    det = _detection_row(status="awaiting_confirm")
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[_round_row()]],
            "user_connections": [[{"provider_email": "recruiter@acme.com"}]],
            "requisitions": [[{"created_by": PROFILE_ID}]],
            "candidates": [[{"id": CANDIDATE_ID}]],
            "candidate_rounds": [[]],
            "recall_bots": [[{"id": "b1", "recall_bot_id": "rb1",
                              "status": "in_call_recording",
                              "transcript_ready": True,
                              "transcript_url": "https://recall.test/t.json"}]],
        },
        write_results={("candidate_rounds", "insert"): [[{"id": CR_ID}]]},
    )

    class _Resp:
        status_code = 200

        def json(self):
            return [{"speaker": "x", "words": []}]

    class _HttpxClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return _Resp()

    feedback_svc = AsyncMock()
    feedback_svc.trigger_feedback_processing = AsyncMock(return_value={})

    with patch.object(h, "get_supabase_admin_client", return_value=fake), \
         patch.object(h.httpx, "AsyncClient", _HttpxClient), \
         _patched_externals(feedback=feedback_svc):
        await h._confirm(DETECTION_ID, ROUND_ID, _action_payload())

    # Transcript upserted + feedback triggered exactly once, against the
    # freshly-inserted candidate_round.
    transcript_writes = [w for w in fake.writes if w[0] == "transcripts"]
    assert transcript_writes
    assert feedback_svc.trigger_feedback_processing.await_count == 1
    # Triggered against the freshly-inserted candidate_round (id from insert result).
    triggered_cr_id = feedback_svc.trigger_feedback_processing.await_args.args[0]
    assert triggered_cr_id == CR_ID
    assert [w for w in fake.writes if w[0] == "candidate_rounds" and w[1] == "insert"]


# ===========================================================================
# _confirm — untracked-import (copy) path
# ===========================================================================


def _untracked_detection(status="awaiting_confirm"):
    det = _detection_row(status=status)
    det["event_start"] = "2000-01-01T00:00:00+00:00"  # already passed
    det["matched_candidate_round_id"] = "prior-cr"
    det["detection_signals"] = {
        "untracked_capture": True,
        "_ui_state": {"current_step": "review", "role_title": "SWE"},
    }
    return det


async def test_confirm_untracked_import_copy_path(captured_blocks):
    det = _untracked_detection()
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[_round_row()]],
            "user_connections": [[{"provider_email": "recruiter@acme.com"}]],
            "requisitions": [[{"created_by": PROFILE_ID}]],
            "candidates": [[{"name": "Jane Doe", "email": "jane@cand.com"}]],  # target lookup
            "recall_bots": [[]],
        }
    )
    import_service = MagicMock()
    import_service.import_untracked_interview = AsyncMock(return_value={
        "target_candidate_round_id": "new-cr",
        "target_candidate_id": CANDIDATE_ID,
        "candidate_created": True,
    })
    with patch.object(h, "get_supabase_admin_client", return_value=fake), \
         patch.object(h, "UntrackedImportService", return_value=import_service), \
         _patched_externals():
        await h._confirm(DETECTION_ID, ROUND_ID, _action_payload())

    import_service.import_untracked_interview.assert_awaited_once()
    # Imported-via-copy => NO direct candidate_rounds insert and NO bot link
    # (the import service owns the CR + bot replacement happens elsewhere).
    assert [w for w in fake.writes if w[0] == "candidate_rounds" and w[1] == "insert"] == []
    ups = _det_updates(fake)
    assert ups[-1][2]["detection_status"] == "confirmed"
    # Prior untracked round is cancelled (prior != new target).
    cr_updates = [w for w in fake.writes if w[0] == "candidate_rounds" and w[1] == "update"]
    assert any(w[2].get("status") == "cancelled" for w in cr_updates)
    # Promotion flags merged into signals.
    assert ups[-1][2]["detection_signals"].get("untracked_capture_promoted") is True


async def test_confirm_untracked_import_conflict_shows_warning(captured_blocks):
    from app.services.untracked_import_service import (
        EXISTING_ROUND_CONFLICT_CODE,
        UntrackedImportError,
    )

    det = _untracked_detection()
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[_round_row()]],
            "user_connections": [[{"provider_email": "recruiter@acme.com"}]],
            "requisitions": [[{"created_by": PROFILE_ID}], [{"role_title": "SWE"}]],
        }
    )
    conflict_detail = {
        "code": EXISTING_ROUND_CONFLICT_CODE,
        "message": "This candidate already has this round.",
        "conflict": {"existing_status": "completed", "has_recording": True,
                     "has_transcript": True, "completed_at": "2025-01-01"},
    }
    import_service = MagicMock()
    import_service.import_untracked_interview = AsyncMock(
        side_effect=UntrackedImportError(409, conflict_detail)
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake), \
         patch.object(h, "UntrackedImportService", return_value=import_service), \
         _patched_externals():
        await h._confirm(DETECTION_ID, ROUND_ID, _action_payload())

    # The conflict warning is rendered with an Override button, and the
    # detection status is rolled back to awaiting_confirm (NOT confirmed).
    rendered = str(captured_blocks[-1])
    assert "cal_intel_override_untracked_import" in rendered
    ups = _det_updates(fake)
    assert ups[-1][2]["detection_status"] == "awaiting_confirm"


async def test_confirm_untracked_import_override_proceeds(captured_blocks):
    det = _untracked_detection()
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[_round_row()]],
            "user_connections": [[{"provider_email": "recruiter@acme.com"}]],
            "requisitions": [[{"created_by": PROFILE_ID}]],
            "candidates": [[{"name": "Jane", "email": "jane@cand.com"}]],
            "recall_bots": [[]],
        }
    )
    import_service = MagicMock()
    import_service.import_untracked_interview = AsyncMock(return_value={
        "target_candidate_round_id": "new-cr",
        "target_candidate_id": CANDIDATE_ID,
        "candidate_created": False,
    })
    with patch.object(h, "get_supabase_admin_client", return_value=fake), \
         patch.object(h, "UntrackedImportService", return_value=import_service), \
         _patched_externals():
        await h._confirm(DETECTION_ID, ROUND_ID, _action_payload(), force_import_override=True)

    # override_existing_round=True propagated.
    _, kwargs = import_service.import_untracked_interview.await_args
    assert kwargs["override_existing_round"] is True
    ups = _det_updates(fake)
    assert ups[-1][2]["detection_status"] == "confirmed"


async def test_confirm_round_foreign_to_matched_req_raises(captured_blocks):
    # detection.matched_requisition_id != round.requisition_id => hard stop.
    det = _detection_row(status="awaiting_confirm", matched_requisition_id="OTHER-REQ")
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[_round_row()]],
            "user_connections": [[{"provider_email": "recruiter@acme.com"}]],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake), _patched_externals():
        with pytest.raises(h.CalendarIntelligenceError):
            await h._confirm(DETECTION_ID, ROUND_ID, _action_payload())
    ups = _det_updates(fake)
    assert ups[-1][2]["detection_status"] == "awaiting_confirm"


async def test_confirm_foreign_requisition_owner_raises(captured_blocks):
    det = _detection_row(status="awaiting_confirm")
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[_round_row()]],
            "user_connections": [[{"provider_email": "recruiter@acme.com"}]],
            "requisitions": [[{"created_by": "someone-else"}]],  # not owner
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake), _patched_externals():
        with pytest.raises(h.CalendarIntelligenceError):
            await h._confirm(DETECTION_ID, ROUND_ID, _action_payload())
