"""BE-T8 characterization tests for the calendar_intelligence_handler undo,
send-prep, reschedule, confirmed-summary, and bot-link chains.

Covers:
  - `_undo` (~300 lines): confirmed->review restore, cr_was_created cancel,
    prior_round_state restore, the two-phase bot cancel, the "DB now lies"
    (sync-after-remote-cancel failure) compensation path, undo CAS conflict.
  - `_send_prep`: interviewer 4-tier recipient resolution, external/domain
    filtering, Slack-DM-then-email fan-out, the `truly_failed` computation,
    and the no-interviewer + no-round branches.
  - `_handle_reschedule_update`: time update + bot reschedule success/failure.
  - `_build_confirmed_summary_blocks`: no-round fallback + full render.
  - `_link_bot_to_candidate_round`: reuse-active-bot + transcript-ready
    feedback trigger.
  - `_update_slack_message`: response_url success + channel fallback.
  - `_build_action_error_blocks`: error-block assembly.

ALL effect boundaries mocked; no production code modified. Quirks are
DOCUMENTED (CHARACTERIZED) and pinned to CURRENT behavior.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

import app.services.calendar_intelligence_handler as h


# --- table-routed fake supabase (same contract as the confirm test) ---


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


PROFILE_ID = "prof-1"
ORG_ID = "org-1"
DETECTION_ID = "det-12345678"
REQ_ID = "r1"
ROUND_ID = "rd1"
CR_ID = "cr-1"


def _detection_row(status="confirmed", **overrides):
    row = {
        "id": DETECTION_ID,
        "profile_id": PROFILE_ID,
        "organization_id": ORG_ID,
        "detection_status": status,
        "event_title": "Jane Doe <> John Smith",
        "event_start": "2099-01-15T14:00:00+00:00",
        "meeting_platform": "zoom",
        "meeting_url": "https://zoom.us/j/1",
        "matched_requisition_id": REQ_ID,
        "matched_candidate_id": "cand-1",
        "matched_candidate_round_id": CR_ID,
        "external_attendees": [{"email": "jane@cand.com", "display_name": "Jane Doe"}],
        "internal_attendees": [
            {"email": "john.smith@acme.com", "display_name": "John Smith", "self": False},
            {"email": "me@acme.com", "display_name": "Me", "self": True},
        ],
        "detection_signals": {"_ui_state": {"current_step": "confirmed", "role_title": "SWE"}},
        "detection_confidence": 0.9,
        "undo_expires_at": "2099-01-01T00:00:00+00:00",
    }
    row.update(overrides)
    return row


def _action_payload(action_id="cal_intel_undo", value=None):
    return {
        "actions": [{"action_id": action_id, "value": json.dumps(value or {"detection_id": DETECTION_ID})}],
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


def _det_updates(fake):
    return [w for w in fake.writes if w[0] == "calendar_event_detections" and w[1] == "update"]


def _patched_recall(recall=None):
    recall = recall or AsyncMock()
    recall.delete_bot = AsyncMock(return_value=True)
    recall.remove_bot_from_call = AsyncMock(return_value=True)
    recall.close = AsyncMock()
    return patch("app.services.recall_service.get_recall_service", return_value=recall), recall


# ===========================================================================
# _undo — happy paths
# ===========================================================================


async def test_undo_cr_was_created_cancels_and_restores_review(captured_blocks):
    det = _detection_row(status="confirmed")
    det["detection_signals"] = {
        "_ui_state": {"current_step": "confirmed", "role_title": "SWE",
                      "selected_requisition_id": REQ_ID, "selected_round_id": ROUND_ID},
        "_undo_metadata": {"cr_was_created": True, "prior_round_state": None},
    }
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "candidate_rounds": [[{"id": CR_ID, "round_id": ROUND_ID, "candidate_id": "cand-1",
                                   "status": "scheduled", "meeting_url": "u", "scheduled_at": "t",
                                   "interviewer_email": None}]],
            "recall_bots": [[{"id": "b1", "recall_bot_id": "rb1", "status": "joining"}]],
            "rounds": [
                [{"id": ROUND_ID, "name": "Technical", "round_number": 1,
                  "duration_minutes": 45, "default_interviewer_emails": []}],
            ],
            "requisitions": [[{"role_title": "SWE"}]],
        }
    )
    patcher, recall = _patched_recall()
    with patch.object(h, "get_supabase_admin_client", return_value=fake), patcher:
        await h._undo(DETECTION_ID, _action_payload())

    # created CR cancelled.
    cr_updates = [w for w in fake.writes if w[0] == "candidate_rounds" and w[1] == "update"]
    assert any(w[2].get("status") == "cancelled" for w in cr_updates)
    # bot deleted remotely + DB synced to cancelled.
    recall.delete_bot.assert_awaited_once_with("rb1")
    bot_updates = [w for w in fake.writes if w[0] == "recall_bots" and w[1] == "update"]
    assert any(w[2].get("status") == "cancelled" for w in bot_updates)
    # detection moved back to a re-actionable state (review since round resolved).
    ups = _det_updates(fake)
    assert ups[-1][2]["detection_status"] == "awaiting_confirm"
    assert ups[-1][2]["undo_expires_at"] is None
    assert "Undone" in str(captured_blocks[-1])


async def test_undo_prior_round_state_restored(captured_blocks):
    det = _detection_row(status="confirmed")
    det["detection_signals"] = {
        "_ui_state": {"current_step": "confirmed", "role_title": "SWE",
                      "selected_requisition_id": REQ_ID, "selected_round_id": ROUND_ID},
        "_undo_metadata": {"cr_was_created": False,
                           "prior_round_state": {"status": "pending", "meeting_url": None,
                                                 "scheduled_at": None, "interviewer_email": None}},
    }
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "candidate_rounds": [[{"id": CR_ID, "round_id": ROUND_ID, "candidate_id": "cand-1",
                                   "status": "scheduled", "meeting_url": "u", "scheduled_at": "t",
                                   "interviewer_email": None}]],
            "recall_bots": [[]],
            "rounds": [[{"id": ROUND_ID, "name": "Technical", "round_number": 1,
                         "duration_minutes": 45, "default_interviewer_emails": []}]],
            "requisitions": [[{"role_title": "SWE"}]],
        }
    )
    patcher, recall = _patched_recall()
    with patch.object(h, "get_supabase_admin_client", return_value=fake), patcher:
        await h._undo(DETECTION_ID, _action_payload())
    # CR restored to its prior status (pending), not cancelled.
    cr_updates = [w for w in fake.writes if w[0] == "candidate_rounds" and w[1] == "update"]
    assert cr_updates[0][2]["status"] == "pending"


async def test_undo_round_rollback_cas_fail_shows_progressed(captured_blocks):
    # CHARACTERIZED: when the CR rollback CAS finds no matching row (the round
    # already progressed), undo aborts with the "round progressed" message and
    # does NOT touch any bots or the detection status.
    det = _detection_row(status="confirmed")
    det["detection_signals"] = {
        "_ui_state": {"current_step": "confirmed"},
        "_undo_metadata": {"cr_was_created": True, "prior_round_state": None},
    }
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "candidate_rounds": [[{"id": CR_ID, "round_id": ROUND_ID, "candidate_id": "cand-1",
                                   "status": "in_progress"}]],
        },
        write_results={("candidate_rounds", "update"): [[]]},  # CAS miss
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h._undo(DETECTION_ID, _action_payload())
    assert "progressed" in str(captured_blocks[-1]).lower()
    # No detection status change.
    assert _det_updates(fake) == []


async def test_undo_bot_db_sync_failure_compensates(captured_blocks):
    # CHARACTERIZED "DB now lies" path: the remote cancel succeeds but the DB
    # update mirroring it raises => bot_cancel_failed flips True => the CR is
    # compensated back to scheduled and the user sees "undo failed: bot".
    det = _detection_row(status="confirmed")
    det["detection_signals"] = {
        "_ui_state": {"current_step": "confirmed"},
        "_undo_metadata": {"cr_was_created": True, "prior_round_state": None},
    }
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "candidate_rounds": [[{"id": CR_ID, "round_id": ROUND_ID, "candidate_id": "cand-1",
                                   "status": "scheduled"}]],
            "recall_bots": [[{"id": "b1", "recall_bot_id": "rb1", "status": "joining"}]],
        },
    )
    # First CR update (the cancel) succeeds (echo); the bot status sync raises.
    fake.raise_on[("recall_bots", "update")] = RuntimeError("db down")
    patcher, recall = _patched_recall()
    with patch.object(h, "get_supabase_admin_client", return_value=fake), patcher:
        await h._undo(DETECTION_ID, _action_payload())
    # Remote delete was attempted.
    recall.delete_bot.assert_awaited_once_with("rb1")
    # CR compensated back to scheduled.
    cr_updates = [w for w in fake.writes if w[0] == "candidate_rounds" and w[1] == "update"]
    assert any(w[2].get("status") == "scheduled" for w in cr_updates)
    assert "could not cancel the recording bot" in str(captured_blocks[-1]).lower()
    # Detection status NEVER flipped (no successful undo CAS).
    assert _det_updates(fake) == []


async def test_undo_cas_conflict_raises(captured_blocks):
    det = _detection_row(status="confirmed")
    det["detection_signals"] = {
        "_ui_state": {"current_step": "confirmed", "selected_requisition_id": REQ_ID,
                      "selected_round_id": ROUND_ID},
        "_undo_metadata": {"cr_was_created": True, "prior_round_state": None},
    }
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "candidate_rounds": [[{"id": CR_ID, "round_id": ROUND_ID, "candidate_id": "cand-1",
                                   "status": "scheduled"}]],
            "recall_bots": [[]],
            "rounds": [[{"id": ROUND_ID, "name": "Technical", "round_number": 1,
                         "duration_minutes": 45, "default_interviewer_emails": []}]],
            "requisitions": [[{"role_title": "SWE"}]],
        },
        # CR cancel succeeds (echo). The final detection undo CAS misses.
        write_results={("calendar_event_detections", "update"): [[]]},
    )
    patcher, _ = _patched_recall()
    with patch.object(h, "get_supabase_admin_client", return_value=fake), patcher:
        with pytest.raises(h.DetectionAlreadyProcessedError):
            await h._undo(DETECTION_ID, _action_payload())


async def test_undo_no_round_restores_detected(captured_blocks):
    # No selected round / no cr round_id => undo lands on the detected step.
    det = _detection_row(status="confirmed", matched_candidate_round_id=None,
                         matched_requisition_id=None)
    det["detection_signals"] = {
        "_ui_state": {"current_step": "confirmed"},
        "_undo_metadata": {"cr_was_created": False, "prior_round_state": None},
    }
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "recall_bots": [[]],
            "requisitions": [[]],  # _build_detected_step_blocks fetch
        }
    )
    patcher, _ = _patched_recall()
    with patch.object(h, "get_supabase_admin_client", return_value=fake), patcher:
        await h._undo(DETECTION_ID, _action_payload())
    ups = _det_updates(fake)
    assert ups[-1][2]["detection_status"] == "awaiting_round"
    assert "Undone" in str(captured_blocks[-1])


# ===========================================================================
# _send_prep — recipient resolution + fan-out
# ===========================================================================


def _prep_detection():
    det = _detection_row(status="confirmed")
    det["internal_attendees"] = [
        {"email": "interviewer@acme.com", "display_name": "Iv", "self": False},
        {"email": "me@acme.com", "display_name": "Me", "self": True},
    ]
    return det


def _prep_fake(*, cr_interviewer="interviewer@acme.com", default_emails=None):
    return _FakeSupabase(
        selects={
            "calendar_event_detections": [[_prep_detection()]],
            "candidate_rounds": [[{"round_id": ROUND_ID, "candidate_id": "cand-1",
                                   "meeting_url": "u", "scheduled_at": "2099-01-15T14:00:00+00:00",
                                   "scheduling_timezone": "America/New_York",
                                   "interviewer_email": cr_interviewer}]],
            "rounds": [[{"name": "Technical", "guidelines": [{"title": "G1", "description": "do x"}],
                         "default_interviewer_emails": default_emails or []}]],
            "candidates": [[{"name": "Jane Doe", "email": "jane@cand.com"}]],
            "requisitions": [[{"role_title": "SWE"}]],
        }
    )


def _patched_slack(slack=None, *, found_user="U-iv"):
    slack = slack or AsyncMock()
    slack.find_slack_user_by_profile_email = AsyncMock(return_value=found_user)
    slack.get_bot_token_for_team = AsyncMock(return_value="xoxb-test")
    slack.send_dm = AsyncMock()
    return patch.object(h, "get_slack_service", return_value=slack), slack


async def test_send_prep_not_confirmed_raises(captured_blocks):
    fake = _FakeSupabase(selects={"calendar_event_detections": [[_detection_row(status="notified")]]})
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.DetectionAlreadyProcessedError):
            await h._send_prep(DETECTION_ID, _action_payload("cal_intel_send_prep"))


async def test_send_prep_no_round_renders_error(captured_blocks):
    det = _detection_row(status="confirmed", matched_candidate_round_id=None)
    fake = _FakeSupabase(selects={"calendar_event_detections": [[det]]})
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h._send_prep(DETECTION_ID, _action_payload("cal_intel_send_prep"))
    assert "No round linked" in str(captured_blocks[-1])


async def test_send_prep_slack_dm_success(captured_blocks):
    fake = _prep_fake()
    slack_patch, slack = _patched_slack(found_user="U-iv")
    with patch.object(h, "get_supabase_admin_client", return_value=fake), slack_patch:
        await h._send_prep(DETECTION_ID, _action_payload("cal_intel_send_prep"))
    slack.send_dm.assert_awaited_once()
    assert "Prep sent via Slack" in str(captured_blocks[-1])


async def test_send_prep_email_fallback_when_no_slack_user(captured_blocks):
    # No Slack user => falls through to email. truly_failed shrinks when email
    # succeeds.
    fake = _prep_fake()
    slack_patch, slack = _patched_slack(found_user=None)
    email_svc = AsyncMock()
    email_svc.send_templated_email = AsyncMock(return_value=type("R", (), {"success": True})())
    with patch.object(h, "get_supabase_admin_client", return_value=fake), slack_patch, \
         patch("app.services.email.service.get_email_service", return_value=email_svc):
        await h._send_prep(DETECTION_ID, _action_payload("cal_intel_send_prep"))
    slack.send_dm.assert_not_awaited()
    email_svc.send_templated_email.assert_awaited_once()
    rendered = str(captured_blocks[-1])
    assert "emailed to" in rendered.lower()
    assert "could not reach" not in rendered.lower()  # email succeeded => not truly_failed


async def test_send_prep_truly_failed_when_email_fails(captured_blocks):
    fake = _prep_fake()
    slack_patch, _ = _patched_slack(found_user=None)
    email_svc = AsyncMock()
    email_svc.send_templated_email = AsyncMock(return_value=type("R", (), {"success": False})())
    with patch.object(h, "get_supabase_admin_client", return_value=fake), slack_patch, \
         patch("app.services.email.service.get_email_service", return_value=email_svc):
        await h._send_prep(DETECTION_ID, _action_payload("cal_intel_send_prep"))
    assert "could not reach" in str(captured_blocks[-1]).lower()


async def test_send_prep_external_attendee_filtered_out(captured_blocks):
    # CHARACTERIZED: an interviewer email that matches an external attendee or
    # is outside the internal domain is filtered, leaving no recipients.
    det = _prep_detection()
    det["external_attendees"] = [{"email": "jane@cand.com", "display_name": "Jane"}]
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            # interviewer_email points at the external candidate => filtered out.
            "candidate_rounds": [[{"round_id": ROUND_ID, "candidate_id": "cand-1",
                                   "meeting_url": "u", "scheduled_at": "t",
                                   "scheduling_timezone": "", "interviewer_email": "jane@cand.com"}]],
            "rounds": [[{"name": "Technical", "guidelines": [], "default_interviewer_emails": []}]],
            "candidates": [[{"name": "Jane", "email": "jane@cand.com"}]],
            "requisitions": [[{"role_title": "SWE"}]],
        }
    )
    slack_patch, slack = _patched_slack()
    with patch.object(h, "get_supabase_admin_client", return_value=fake), slack_patch:
        await h._send_prep(DETECTION_ID, _action_payload("cal_intel_send_prep"))
    # No interviewer survived filtering => the "no interviewer email found" card.
    assert "No interviewer email found" in str(captured_blocks[-1])
    slack.send_dm.assert_not_awaited()


# ===========================================================================
# _handle_reschedule_update
# ===========================================================================


async def test_reschedule_update_no_new_start_no_op(captured_blocks):
    await h._handle_reschedule_update(DETECTION_ID, "", _action_payload("cal_intel_reschedule_update"))
    assert captured_blocks == []


async def test_reschedule_update_not_confirmed_raises(captured_blocks):
    fake = _FakeSupabase(selects={"calendar_event_detections": [[_detection_row(status="notified")]]})
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.DetectionAlreadyProcessedError):
            await h._handle_reschedule_update(
                DETECTION_ID, "2099-02-02T10:00:00+00:00", _action_payload("cal_intel_reschedule_update")
            )


async def test_reschedule_update_success_redeploys_bot(captured_blocks):
    det = _detection_row(status="confirmed")
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "recall_bots": [
                [{"id": "b1", "recall_bot_id": "rb1", "status": "joining"}],  # old bot to cancel
                [{"id": "b2"}],                                                # new bot lookup
            ],
            "candidate_rounds": [[{"round_id": ROUND_ID, "candidate_id": "cand-1",
                                   "interviewer_email": "interviewer@acme.com"}]],  # summary fetch
            "rounds": [[{"name": "Technical"}]],
            "candidates": [[{"name": "Jane", "email": "jane@cand.com"}]],
            "requisitions": [[{"role_title": "SWE"}]],
        }
    )
    recall = AsyncMock()
    recall.delete_bot = AsyncMock(return_value=True)
    with patch.object(h, "get_supabase_admin_client", return_value=fake), \
         patch("app.services.recall_service.get_recall_service", return_value=recall), \
         patch("app.services.recall_service.schedule_or_replace_recall_bot", new=AsyncMock()):
        await h._handle_reschedule_update(
            DETECTION_ID, "2099-02-02T10:00:00+00:00", _action_payload("cal_intel_reschedule_update")
        )
    # CR scheduled_at updated.
    cr_updates = [w for w in fake.writes if w[0] == "candidate_rounds" and w[1] == "update"]
    assert cr_updates[0][2]["scheduled_at"] == "2099-02-02T10:00:00+00:00"
    # New bot relinked to the detection.
    bot_updates = [w for w in fake.writes if w[0] == "recall_bots" and w[1] == "update"]
    assert any(w[2].get("detection_id") == DETECTION_ID for w in bot_updates)
    assert "time updated in OpenRecruiting" in str(captured_blocks[-1])


async def test_reschedule_update_bot_failure_reports(captured_blocks):
    det = _detection_row(status="confirmed")
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "recall_bots": [[{"id": "b1", "recall_bot_id": "rb1", "status": "joining"}]],
            "candidate_rounds": [[{"round_id": ROUND_ID, "candidate_id": "cand-1",
                                   "interviewer_email": "interviewer@acme.com"}]],
            "rounds": [[{"name": "Technical"}]],
            "candidates": [[{"name": "Jane", "email": "jane@cand.com"}]],
            "requisitions": [[{"role_title": "SWE"}]],
        }
    )
    recall = AsyncMock()
    recall.delete_bot = AsyncMock(side_effect=RuntimeError("recall down"))
    with patch.object(h, "get_supabase_admin_client", return_value=fake), \
         patch("app.services.recall_service.get_recall_service", return_value=recall), \
         patch("app.services.recall_service.schedule_or_replace_recall_bot", new=AsyncMock()):
        await h._handle_reschedule_update(
            DETECTION_ID, "2099-02-02T10:00:00+00:00", _action_payload("cal_intel_reschedule_update")
        )
    assert "bot reschedule failed" in str(captured_blocks[-1]).lower()


# ===========================================================================
# _build_confirmed_summary_blocks
# ===========================================================================


async def test_confirmed_summary_no_cr_fallback():
    det = _detection_row(status="confirmed", matched_candidate_round_id=None)
    fake = _FakeSupabase()
    blocks = await h._build_confirmed_summary_blocks(det, fake, [":x: note"], include_send_prep=False)
    rendered = str(blocks)
    assert "note" in rendered
    # CHARACTERIZED: fallback Undo button uses an f-string-built JSON value
    # (a literal JSON string), not a json.dumps() call.
    assert '{"detection_id": "det-1234' in rendered


async def test_confirmed_summary_full_render():
    det = _detection_row(status="confirmed")
    fake = _FakeSupabase(
        selects={
            "candidate_rounds": [[{"round_id": ROUND_ID, "candidate_id": "cand-1",
                                   "interviewer_email": "interviewer@acme.com"}]],
            "rounds": [[{"name": "Technical"}]],
            "candidates": [[{"name": "Jane Doe", "email": "jane@cand.com"}]],
            "requisitions": [[{"role_title": "SWE"}]],
        }
    )
    blocks = await h._build_confirmed_summary_blocks(det, fake, [":white_check_mark: done"],
                                                     include_send_prep=False)
    assert "done" in str(blocks)


# ===========================================================================
# _link_bot_to_candidate_round
# ===========================================================================


async def test_link_bot_reuses_active_bot():
    fake = _FakeSupabase(
        selects={
            "recall_bots": [[{"id": "b1", "recall_bot_id": "rb1", "status": "joining",
                              "transcript_ready": False, "transcript_url": None}]],
        }
    )
    ok = await h._link_bot_to_candidate_round(DETECTION_ID, CR_ID, fake)
    assert ok is True
    bot_updates = [w for w in fake.writes if w[0] == "recall_bots" and w[1] == "update"]
    assert bot_updates[0][2]["candidate_round_id"] == CR_ID


async def test_link_bot_transcript_ready_triggers_feedback():
    fake = _FakeSupabase(
        selects={
            "recall_bots": [[{"id": "b1", "recall_bot_id": "rb1",
                              "status": "in_call_recording", "transcript_ready": True,
                              "transcript_url": "https://recall.test/t.json"}]],
        }
    )

    class _Resp:
        status_code = 200

        def json(self):
            return [{"speaker": "x"}]

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
    with patch.object(h.httpx, "AsyncClient", _HttpxClient), \
         patch("app.services.feedback_job_service.get_feedback_job_service", return_value=feedback_svc):
        ok = await h._link_bot_to_candidate_round(DETECTION_ID, CR_ID, fake)
    assert ok is True
    assert [w for w in fake.writes if w[0] == "transcripts"]
    feedback_svc.trigger_feedback_processing.assert_awaited_once_with(CR_ID)


async def test_link_bot_no_active_no_meeting_url_returns_false():
    # NB: the no-active-bots branch re-fetches the detection via
    # _get_detection (which uses get_supabase_admin_client, NOT the passed
    # supabase), so that factory must be patched too.
    det = _detection_row(meeting_url="")
    fake = _FakeSupabase(
        selects={
            "recall_bots": [[]],
            "calendar_event_detections": [[det]],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        ok = await h._link_bot_to_candidate_round(DETECTION_ID, CR_ID, fake)
    assert ok is False


# ===========================================================================
# _update_slack_message — response_url + channel fallback
# ===========================================================================


async def test_update_slack_message_response_url_success(monkeypatch):
    posted = {}

    class _Resp:
        is_success = True
        status_code = 200

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            posted["url"] = url
            posted["json"] = json
            return _Resp()

    monkeypatch.setattr(h.httpx, "AsyncClient", _Client)
    await h._update_slack_message({"response_url": "https://hooks.slack/r"}, [{"type": "section"}])
    assert posted["url"] == "https://hooks.slack/r"
    assert posted["json"]["replace_original"] is True


async def test_update_slack_message_channel_fallback(monkeypatch):
    # No response_url => falls back to the channel update via slack service.
    slack = AsyncMock()
    slack.get_bot_token_for_team = AsyncMock(return_value="xoxb")
    slack.update_message = AsyncMock()
    monkeypatch.setattr(h, "get_slack_service", lambda: slack)
    await h._update_slack_message(
        {"channel": {"id": "C1"}, "message": {"ts": "1.2"}, "team": {"id": "T1"}},
        [{"type": "section"}],
    )
    slack.update_message.assert_awaited_once()


# ===========================================================================
# _build_action_error_blocks
# ===========================================================================


async def test_build_action_error_blocks_no_detection_id_uses_plain_error():
    blocks = await h._build_action_error_blocks("", "boom", scope="action")
    assert "boom" in str(blocks)


async def test_build_action_error_blocks_with_detection_renders_retry():
    det = _detection_row(status="awaiting_round")
    det["detection_signals"] = {"_ui_state": {"current_step": "round_select"}}
    fake = _FakeSupabase(selects={"calendar_event_detections": [[det]]})
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        blocks = await h._build_action_error_blocks(DETECTION_ID, "boom", scope="action")
    rendered = str(blocks)
    assert "boom" in rendered
    assert "cal_intel_retry_match" in rendered


# ===========================================================================
# _back_to_round — navigation pop from review back to round selection
# ===========================================================================


async def test_back_to_round_pops_to_round_select(captured_blocks):
    det = _detection_row(status="awaiting_confirm")
    det["detection_signals"] = {
        "_ui_state": {
            "current_step": "review",
            "selected_requisition_id": REQ_ID,
            "selected_round_id": ROUND_ID,
            "role_title": "SWE",
            "state_stack": [
                {"step": "role_select"},
                {"step": "round_select", "selected_requisition_id": REQ_ID, "role_title": "SWE"},
            ],
        }
    }
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[{"id": ROUND_ID, "name": "Technical", "round_number": 1,
                         "duration_minutes": 45, "default_interviewer_emails": []}]],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h._back_to_round(DETECTION_ID, _action_payload("cal_intel_back_round"))
    ups = _det_updates(fake)
    persisted = ups[-1][2]["detection_signals"]["_ui_state"]
    assert persisted["current_step"] == "round_select"
    assert persisted["selected_requisition_id"] == REQ_ID
    # awaiting_confirm rolled back to awaiting_round.
    assert any(w[2].get("detection_status") == "awaiting_round" for w in ups)


async def test_back_to_round_no_stack_refetches_rounds_from_req(captured_blocks):
    # CHARACTERIZED: empty state_stack + a matched requisition => _back_to_round
    # re-fetches the live rounds for that req and re-renders the round step.
    det = _detection_row(status="awaiting_confirm", matched_requisition_id=REQ_ID)
    det["detection_signals"] = {
        "_ui_state": {"current_step": "review", "role_title": "SWE",
                      "selected_requisition_id": REQ_ID, "state_stack": []}
    }
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[{"id": ROUND_ID, "name": "Technical", "round_number": 1,
                         "duration_minutes": 45, "default_interviewer_emails": []}]],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h._back_to_round(DETECTION_ID, _action_payload("cal_intel_back_round"))
    ups = _det_updates(fake)
    persisted = ups[-1][2]["detection_signals"]["_ui_state"]
    assert persisted["current_step"] == "round_select"
    assert len(persisted["round_candidates"]) == 1


# ===========================================================================
# Bot-replacement helpers (untracked confirm path)
# ===========================================================================


async def test_cancel_detection_bots_for_replacement_cancels_active():
    fake = _FakeSupabase(
        selects={
            "recall_bots": [[{"id": "b1", "recall_bot_id": "rb1", "status": "in_call_recording"}]],
        }
    )
    recall = AsyncMock()
    recall.remove_bot_from_call = AsyncMock(return_value=True)
    recall.close = AsyncMock()
    with patch("app.services.recall_service.get_recall_service", return_value=recall):
        ok = await h._cancel_detection_bots_for_replacement(DETECTION_ID, fake)
    assert ok is True
    recall.remove_bot_from_call.assert_awaited_once_with("rb1")
    bot_updates = [w for w in fake.writes if w[0] == "recall_bots" and w[1] == "update"]
    assert bot_updates[0][2]["status"] == "cancelled"


async def test_cancel_detection_bots_for_replacement_no_bots_ok():
    fake = _FakeSupabase(selects={"recall_bots": [[]]})
    ok = await h._cancel_detection_bots_for_replacement(DETECTION_ID, fake)
    assert ok is True


async def test_cancel_detection_bots_remote_failure_keeps_db():
    # CHARACTERIZED: when the remote cancel returns False, the DB row is left
    # untouched and the function reports all_ok=False.
    fake = _FakeSupabase(
        selects={"recall_bots": [[{"id": "b1", "recall_bot_id": "rb1", "status": "joining"}]]}
    )
    recall = AsyncMock()
    recall.delete_bot = AsyncMock(return_value=False)
    recall.close = AsyncMock()
    with patch("app.services.recall_service.get_recall_service", return_value=recall):
        ok = await h._cancel_detection_bots_for_replacement(DETECTION_ID, fake)
    assert ok is False
    assert [w for w in fake.writes if w[0] == "recall_bots"] == []


async def test_deploy_fresh_detection_bot_links_new():
    det = _detection_row()
    fake = _FakeSupabase(
        selects={
            "recall_bots": [[{"id": "b2", "status": "created"}]],
        }
    )
    with patch("app.services.recall_service.schedule_or_replace_recall_bot", new=AsyncMock()):
        ok = await h._deploy_fresh_detection_bot(det, CR_ID, fake)
    assert ok is True
    bot_updates = [w for w in fake.writes if w[0] == "recall_bots" and w[1] == "update"]
    assert bot_updates[0][2]["detection_id"] == DETECTION_ID
    assert bot_updates[0][2]["source"] == "calendar_intelligence"


async def test_deploy_fresh_detection_bot_no_meeting_url_false():
    det = _detection_row(meeting_url="")
    fake = _FakeSupabase()
    ok = await h._deploy_fresh_detection_bot(det, CR_ID, fake)
    assert ok is False


async def test_deploy_fresh_detection_bot_no_bot_found_false():
    det = _detection_row()
    fake = _FakeSupabase(selects={"recall_bots": [[]]})  # deploy then lookup empty
    with patch("app.services.recall_service.schedule_or_replace_recall_bot", new=AsyncMock()):
        ok = await h._deploy_fresh_detection_bot(det, CR_ID, fake)
    assert ok is False


async def test_replace_untracked_detection_bot_full():
    det = _detection_row()
    fake = _FakeSupabase(
        selects={
            "recall_bots": [
                [{"id": "b1", "recall_bot_id": "rb1", "status": "joining"}],  # cancel phase
                [{"id": "b2", "status": "created"}],                          # deploy lookup
            ],
        }
    )
    recall = AsyncMock()
    recall.delete_bot = AsyncMock(return_value=True)
    recall.close = AsyncMock()
    with patch("app.services.recall_service.get_recall_service", return_value=recall), \
         patch("app.services.recall_service.schedule_or_replace_recall_bot", new=AsyncMock()):
        ok = await h._replace_untracked_detection_bot(det, CR_ID, fake)
    assert ok is True


async def test_link_detection_bot_for_confirm_routes_untracked():
    det = _detection_row()
    det["detection_signals"] = {"untracked_capture": True}
    fake = _FakeSupabase(selects={"recall_bots": [[]]})  # no bots => cancel ok early
    recall = AsyncMock()
    recall.close = AsyncMock()
    with patch("app.services.recall_service.get_recall_service", return_value=recall), \
         patch("app.services.recall_service.schedule_or_replace_recall_bot", new=AsyncMock()):
        # No bots to cancel => cancel_ok True, then deploy needs a bot row.
        fake.selects["recall_bots"] = [[], [{"id": "b2", "status": "created"}]]
        ok = await h._link_detection_bot_for_confirm(det, CR_ID, fake)
    assert ok is True


# ===========================================================================
# handle_cal_intel_action — routing for the confirmed-state acks
# ===========================================================================


async def test_dispatch_ack_attendee_change_renders_summary(captured_blocks):
    det = _detection_row(status="confirmed")
    fake = _FakeSupabase(
        selects={
            # auth: owner lookup, then _get_detection, then summary fetches
            "calendar_event_detections": [
                [{"profile_id": PROFILE_ID}],
                [det],
            ],
            "slack_connections": [[{"profile_id": PROFILE_ID}]],
            "candidate_rounds": [[{"round_id": ROUND_ID, "candidate_id": "cand-1",
                                   "interviewer_email": "interviewer@acme.com"}]],
            "rounds": [[{"name": "Technical"}]],
            "candidates": [[{"name": "Jane", "email": "jane@cand.com"}]],
            "requisitions": [[{"role_title": "SWE"}]],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h.handle_cal_intel_action(
            "cal_intel_ack_attendee_change", _action_payload("cal_intel_ack_attendee_change")
        )
    assert "Attendee change acknowledged" in str(captured_blocks[-1])


async def test_dispatch_reschedule_ack_non_confirmed_swallowed(captured_blocks):
    # reschedule_ack on a non-confirmed detection raises
    # DetectionAlreadyProcessedError, which the dispatcher swallows silently.
    det = _detection_row(status="notified")
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [
                [{"profile_id": PROFILE_ID}],
                [det],
            ],
            "slack_connections": [[{"profile_id": PROFILE_ID}]],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h.handle_cal_intel_action(
            "cal_intel_reschedule_ack", _action_payload("cal_intel_reschedule_ack")
        )
    # Swallowed => no blocks rendered.
    assert captured_blocks == []


async def test_dispatch_open_dashboard_no_op(captured_blocks):
    det = _detection_row(status="confirmed")
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[{"profile_id": PROFILE_ID}]],
            "slack_connections": [[{"profile_id": PROFILE_ID}]],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h.handle_cal_intel_action(
            "cal_intel_open_dashboard", _action_payload("cal_intel_open_dashboard")
        )
    assert captured_blocks == []


async def test_dispatch_maps_generic_error_to_action_block(captured_blocks):
    # A generic CalendarIntelligenceError from _confirm maps to the "action"
    # scope error block with a retry button.
    det = _detection_row(status="awaiting_confirm", matched_requisition_id="OTHER")
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [
                [{"profile_id": PROFILE_ID}],   # auth owner
                [det],                           # _confirm _get_detection
                [det],                           # _build_action_error_blocks _get_detection
            ],
            "slack_connections": [[{"profile_id": PROFILE_ID}]],
            "rounds": [[{"id": ROUND_ID, "name": "Technical", "requisition_id": REQ_ID,
                         "round_number": 1, "default_interviewer_emails": []}]],
            "user_connections": [[{"provider_email": "recruiter@acme.com"}]],
        }
    )
    recall = AsyncMock()
    recall.delete_bot = AsyncMock(return_value=True)
    recall.close = AsyncMock()
    with patch.object(h, "get_supabase_admin_client", return_value=fake), \
         patch("app.services.recall_service.get_recall_service", return_value=recall):
        await h.handle_cal_intel_action(
            "cal_intel_confirm",
            _action_payload("cal_intel_confirm", {"detection_id": DETECTION_ID, "round_id": ROUND_ID}),
        )
    rendered = str(captured_blocks[-1])
    assert "cal_intel_retry_match" in rendered
