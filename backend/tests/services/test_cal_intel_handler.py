"""BE-T2 characterization tests for calendar_intelligence_handler.

Pins CURRENT behavior of the Slack action/modal state machine: the
`handle_cal_intel_action` dispatch (feature-flag gate, owner-authorization
gate, unknown action), the pure helper functions, and the main state
transitions (select_role → select_round → review; dismiss; not_interview;
disambiguation gates; CAS-conflict "already processed" paths).

Effect boundaries are mocked: Supabase via a table-routed fake recorder,
Slack message updates via a captured stub. No production code is modified.
If a genuine bug is found it is DOCUMENTED in the report and the test asserts
CURRENT behavior (marked with a comment), never the desired behavior.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

import app.services.calendar_intelligence_handler as h


# ===========================================================================
# Table-routed fake Supabase (queued selects + write recorder)
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

    # Filter / ordering chain — all no-ops for routing.
    def eq(self, *_a, **_k):
        return self

    def neq(self, *_a, **_k):
        return self

    def in_(self, *_a, **_k):
        return self

    def is_(self, *_a, **_k):
        return self

    def ilike(self, *_a, **_k):
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
            # Per-(table,op) write-result override controls CAS hit/miss.
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
        # table -> list of result-lists (FIFO per call)
        self.selects = {k: list(v) for k, v in (selects or {}).items()}
        # (table, op) -> list of result-lists controlling CAS .data
        self.write_results = {k: list(v) for k, v in (write_results or {}).items()}
        self.raise_on = {}
        self.writes = []

    def table(self, name):
        return _FakeQuery(self, name)


# ===========================================================================
# Shared fixtures
# ===========================================================================


PROFILE_ID = "prof-1"
DETECTION_ID = "det-12345678"


def _detection_row(status="notified", **overrides):
    row = {
        "id": DETECTION_ID,
        "profile_id": PROFILE_ID,
        "organization_id": "org-1",
        "detection_status": status,
        "event_title": "Jane Doe <> John Smith",
        "event_start": "2025-01-15T14:00:00+00:00",
        "meeting_platform": "zoom",
        "meeting_url": "https://zoom.us/j/1",
        "matched_requisition_id": None,
        "matched_candidate_round_id": None,
        "external_attendees": [{"email": "jane@cand.com", "display_name": "Jane Doe"}],
        "internal_attendees": [
            {"email": "john.smith@acme.com", "display_name": "John Smith", "self": True}
        ],
        "detection_signals": {},
        "detection_confidence": 0.9,
    }
    row.update(overrides)
    return row


def _action_payload(action_id, value=None, *, user_id="slack-user-1", team_id="T1"):
    return {
        "actions": [{"action_id": action_id, "value": json.dumps(value or {"detection_id": DETECTION_ID})}],
        "user": {"id": user_id},
        "team": {"id": team_id},
        "response_url": "https://hooks.slack.test/r",
        "channel": {"id": "C1"},
        "message": {"ts": "111.222"},
    }


@pytest.fixture
def captured_blocks(monkeypatch):
    """Capture blocks passed to _update_slack_message; suppress real Slack/httpx."""
    captured = []

    async def _fake_update(payload, blocks):
        captured.append(blocks)

    monkeypatch.setattr(h, "_update_slack_message", _fake_update)
    return captured


# ===========================================================================
# Pure helpers
# ===========================================================================


def test_extract_value_from_action_button_value():
    action = {"value": json.dumps({"detection_id": "d", "requisition_id": "r"})}
    assert h._extract_value_from_action(action) == {"detection_id": "d", "requisition_id": "r"}


def test_extract_value_from_action_selected_option_json():
    action = {"selected_option": {"value": json.dumps({"detection_id": "d"})}}
    assert h._extract_value_from_action(action) == {"detection_id": "d"}


def test_extract_value_from_action_selected_option_bare_id():
    # CHARACTERIZED: a non-JSON selected_option value is treated as a bare
    # requisition_id (legacy static_select fallback).
    action = {"selected_option": {"value": "req-bare"}}
    assert h._extract_value_from_action(action) == {"requisition_id": "req-bare"}


def test_extract_value_from_action_empty():
    assert h._extract_value_from_action({}) == {}


def test_back_action_for_ui_step():
    assert h._back_action_for_ui_step("d", "review")["action_id"] == "cal_intel_back_round"
    assert h._back_action_for_ui_step("d", "round_select")["action_id"] == "cal_intel_back_role"
    assert h._back_action_for_ui_step("d", "role_select")["action_id"] == "cal_intel_back_detected"
    assert h._back_action_for_ui_step("d", "detected") is None


def test_normalize_attendee_email():
    assert h._normalize_attendee_email("  JANE@X.COM ") == "jane@x.com"
    assert h._normalize_attendee_email(None) == ""


def test_candidate_options_from_detection_dedup():
    detection = {
        "external_attendees": [
            {"email": "A@x.com", "display_name": "Alice"},
            {"email": "a@x.com", "display_name": "Dup"},  # dup after normalize
            {"email": "no-at", "display_name": "Bad"},
            {"email": "b@x.com", "display_name": "Bob"},
        ]
    }
    opts = h._candidate_options_from_detection(detection)
    assert [o["email"] for o in opts] == ["a@x.com", "b@x.com"]


def test_selected_candidate_email_validates_against_options():
    opts = [{"email": "a@x.com"}, {"email": "b@x.com"}]
    assert h._selected_candidate_email({"selected_candidate_email": "a@x.com"}, opts) == "a@x.com"
    # Not in options → ""
    assert h._selected_candidate_email({"selected_candidate_email": "z@x.com"}, opts) == ""


def test_sync_selected_candidate_email_single_option_autoselects():
    ui_state = {}
    detection = {"external_attendees": [{"email": "only@x.com", "display_name": "O"}]}
    selected = h._sync_selected_candidate_email(ui_state, detection)
    assert selected == "only@x.com"
    assert ui_state["selected_candidate_email"] == "only@x.com"


def test_sync_selected_candidate_email_multi_keeps_unset():
    ui_state = {}
    detection = {
        "external_attendees": [
            {"email": "a@x.com", "display_name": "A"},
            {"email": "b@x.com", "display_name": "B"},
        ]
    }
    selected = h._sync_selected_candidate_email(ui_state, detection)
    assert selected == ""  # never silently pick when ambiguous


def test_candidate_option_label_truncates():
    label = h._candidate_option_label("X" * 100, "y@x.com")
    assert len(label) == 75


def test_minimal_role_candidates_caps_and_skips_idless():
    reqs = [{"id": f"r{i}", "role_title": "R"} for i in range(150)]
    reqs.append({"role_title": "no-id"})
    out = h._minimal_role_candidates(reqs)
    assert len(out) == h.MAX_PERSISTED_ROLE_CANDIDATES
    assert all(c["id"] for c in out)


def test_minimal_round_candidates_defaults():
    out = h._minimal_round_candidates([{"id": "rd1", "name": "Tech"}, {"no_id": 1}])
    assert len(out) == 1
    assert out[0]["duration_minutes"] == 45
    assert out[0]["default_interviewer_emails"] == []


def test_read_ui_state_initializes_defaults():
    signals, ui_state = h._read_ui_state({"detection_signals": {}})
    assert ui_state["current_step"] == "detected"
    assert ui_state["state_stack"] == []


def test_push_pop_ui_state_roundtrip():
    ui_state = {"current_step": "role_select", "selected_requisition_id": "r1", "state_stack": []}
    h._push_ui_state(ui_state)
    assert len(ui_state["state_stack"]) == 1
    popped = h._pop_ui_state(ui_state)
    assert popped["step"] == "role_select"
    assert popped["selected_requisition_id"] == "r1"


def test_pop_ui_state_targeted_step():
    ui_state = {"state_stack": [{"step": "role_select"}, {"step": "round_select"}]}
    popped = h._pop_ui_state(ui_state, step="role_select")
    assert popped["step"] == "role_select"
    # The stack was rewound past round_select.
    assert ui_state["state_stack"] == []


def test_pop_ui_state_missing_step_restores_stack():
    original = [{"step": "role_select"}]
    ui_state = {"state_stack": list(original)}
    assert h._pop_ui_state(ui_state, step="nonexistent") is None
    assert ui_state["state_stack"] == original


def test_snapshot_current_ui_state_excludes_candidate_arrays():
    # Codex Round 8 invariant: snapshots must NOT embed candidate arrays.
    ui_state = {
        "current_step": "round_select",
        "selected_requisition_id": "r1",
        "role_candidates": [{"id": "x"}] * 50,
        "round_candidates": [{"id": "y"}] * 50,
    }
    snap = h._snapshot_current_ui_state(ui_state)
    assert "role_candidates" not in snap
    assert "round_candidates" not in snap
    assert snap["selected_requisition_id"] == "r1"


def test_snapshot_current_ui_state_no_step_none():
    assert h._snapshot_current_ui_state({"current_step": ""}) is None


def test_trim_ui_state_drops_state_stack_when_oversized():
    big_stack = [{"step": "x", "blob": "z" * 1000} for _ in range(200)]
    ui_state = {"current_step": "review", "state_stack": big_stack, "role_candidates": []}
    trimmed = h._trim_ui_state_if_oversized(ui_state)
    assert trimmed["state_stack"] == []


def test_trim_ui_state_noop_when_small():
    ui_state = {"current_step": "review", "state_stack": [{"step": "x"}]}
    assert h._trim_ui_state_if_oversized(ui_state) is ui_state


def test_extract_role_match_req_ids_from_scores_dict():
    meta = {"scores": {"r1": 0.9, "r2": 0.4}, "matched_requisition_id": "r3"}
    ids = h._extract_role_match_req_ids(meta)
    assert set(ids) == {"r1", "r2", "r3"}


def test_extract_role_match_req_ids_none():
    assert h._extract_role_match_req_ids(None) == []


def test_extract_existing_round_conflict_detail():
    from app.services.untracked_import_service import EXISTING_ROUND_CONFLICT_CODE
    detail = {"code": EXISTING_ROUND_CONFLICT_CODE, "message": "dup", "conflict": {"existing_status": "completed"}}
    out = h._extract_existing_round_conflict_detail(detail)
    assert out["message"] == "dup"
    assert out["conflict"]["existing_status"] == "completed"


def test_extract_existing_round_conflict_detail_wrong_code():
    assert h._extract_existing_round_conflict_detail({"code": "other"}) is None


def test_is_untracked_capture_detection():
    assert h._is_untracked_capture_detection(
        {"detection_signals": {"untracked_capture": True}}
    ) is True
    assert h._is_untracked_capture_detection({"detection_signals": {}}) is False


def test_event_start_has_passed():
    past = {"event_start": "2000-01-01T00:00:00+00:00"}
    future = {"event_start": "2999-01-01T00:00:00+00:00"}
    assert h._event_start_has_passed(past) is True
    assert h._event_start_has_passed(future) is False


# ===========================================================================
# handle_cal_intel_action — dispatch gates
# ===========================================================================


async def test_dispatch_feature_flag_disabled(captured_blocks, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "CALENDAR_INTELLIGENCE_ENABLED", False)
    with patch.object(h, "get_settings", return_value=settings):
        await h.handle_cal_intel_action("cal_intel_dismiss", _action_payload("cal_intel_dismiss"))
    assert captured_blocks
    assert "temporarily disabled" in str(captured_blocks[-1])


async def test_dispatch_missing_detection_id_no_op(captured_blocks):
    payload = {"actions": [{"action_id": "cal_intel_dismiss", "value": "{}"}], "user": {"id": "u"}}
    await h.handle_cal_intel_action("cal_intel_dismiss", payload)
    assert captured_blocks == []


async def test_dispatch_unauthorized_actor(captured_blocks):
    # Detection owned by prof-1; actor's slack connection resolves to a
    # different profile → permission denied, no state change.
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[{"profile_id": PROFILE_ID}]],
            "slack_connections": [[{"profile_id": "other-prof"}]],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h.handle_cal_intel_action(
            "cal_intel_dismiss", _action_payload("cal_intel_dismiss")
        )
    assert "don't have permission" in str(captured_blocks[-1])


async def test_dispatch_unknown_action_no_blocks(captured_blocks):
    # Owner authorized; unknown action_id falls through to the warning branch.
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[{"profile_id": PROFILE_ID}]],
            "slack_connections": [[{"profile_id": PROFILE_ID}]],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h.handle_cal_intel_action(
            "cal_intel_bogus_action", _action_payload("cal_intel_bogus_action")
        )
    assert captured_blocks == []


# ===========================================================================
# _dismiss / _not_interview — terminal transitions + CAS guard
# ===========================================================================


async def test_dismiss_happy_path(captured_blocks):
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[_detection_row(status="notified")]],
            "recall_bots": [[]],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h._dismiss(DETECTION_ID, _action_payload("cal_intel_dismiss"))

    # Wrote the dismissed status via CAS.
    det_updates = [w for w in fake.writes if w[0] == "calendar_event_detections" and w[1] == "update"]
    assert det_updates
    assert det_updates[-1][2]["detection_status"] == "dismissed"
    assert "Dismissed" in str(captured_blocks[-1])


async def test_dismiss_terminal_status_raises_already_processed(captured_blocks):
    fake = _FakeSupabase(
        selects={"calendar_event_detections": [[_detection_row(status="confirmed")]]}
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.DetectionAlreadyProcessedError):
            await h._dismiss(DETECTION_ID, _action_payload("cal_intel_dismiss"))


async def test_dismiss_cas_conflict_raises(captured_blocks):
    # CAS update returns empty .data (someone else moved the row) → already processed.
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[_detection_row(status="notified")]],
            "recall_bots": [[]],
        },
        write_results={("calendar_event_detections", "update"): [[]]},
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.DetectionAlreadyProcessedError):
            await h._dismiss(DETECTION_ID, _action_payload("cal_intel_dismiss"))


async def test_not_interview_happy_path(captured_blocks):
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[_detection_row(status="notified")]],
            "recall_bots": [[]],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h._not_interview(DETECTION_ID, _action_payload("cal_intel_not_interview"))
    det_updates = [w for w in fake.writes if w[0] == "calendar_event_detections" and w[1] == "update"]
    assert det_updates[-1][2]["detection_status"] == "not_interview"
    assert "Not an interview" in str(captured_blocks[-1])


async def test_not_interview_terminal_raises(captured_blocks):
    fake = _FakeSupabase(
        selects={"calendar_event_detections": [[_detection_row(status="dismissed")]]}
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.DetectionAlreadyProcessedError):
            await h._not_interview(DETECTION_ID, _action_payload("cal_intel_not_interview"))


# ===========================================================================
# _select_role — change-role list path, requisition selection, CAS, ownership
# ===========================================================================


async def test_select_role_change_role_no_open_reqs(captured_blocks):
    # requisition_id=None ("Change Role"); no open reqs → error block.
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[_detection_row(status="notified")]],
            "requisitions": [[]],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h._select_role(DETECTION_ID, None, _action_payload("cal_intel_change_role"))
    assert "No open roles found" in str(captured_blocks[-1])


async def test_select_role_change_role_lists_roles(captured_blocks):
    reqs = [
        {"id": "r1", "role_title": "SWE", "role_location": "Remote", "status": "open", "created_at": "2025-01-01"},
        {"id": "r2", "role_title": "PM", "role_location": "NYC", "status": "open", "created_at": "2025-01-02"},
    ]
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[_detection_row(status="notified")]],
            "requisitions": [list(reqs)],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h._select_role(DETECTION_ID, None, _action_payload("cal_intel_change_role"))
    # Role-selection step blocks rendered; ui_state persisted to role_select.
    det_updates = [w for w in fake.writes if w[0] == "calendar_event_detections" and w[1] == "update"]
    persisted = det_updates[-1][2]["detection_signals"]["_ui_state"]
    assert persisted["current_step"] == "role_select"
    assert len(persisted["role_candidates"]) == 2


async def test_select_role_terminal_status_raises(captured_blocks):
    fake = _FakeSupabase(
        selects={"calendar_event_detections": [[_detection_row(status="confirmed")]]}
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.DetectionAlreadyProcessedError):
            await h._select_role(DETECTION_ID, "r1", _action_payload("cal_intel_select_role"))


async def test_select_role_deleted_requisition_raises(captured_blocks):
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[_detection_row(status="notified")]],
            "requisitions": [[]],  # requisition lookup empty → deleted
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.RequisitionDeletedError):
            await h._select_role(DETECTION_ID, "r1", _action_payload("cal_intel_select_role"))


async def test_select_role_foreign_requisition_raises(captured_blocks):
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[_detection_row(status="notified")]],
            "requisitions": [[{"id": "r1", "role_title": "SWE", "created_by": "someone-else"}]],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.CalendarIntelligenceError):
            await h._select_role(DETECTION_ID, "r1", _action_payload("cal_intel_select_role"))


async def test_select_role_selection_advances_to_round_step(captured_blocks):
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[_detection_row(status="notified")]],
            "requisitions": [
                [{"id": "r1", "role_title": "SWE", "created_by": PROFILE_ID}],   # ownership lookup
            ],
            "rounds": [
                [{"id": "rd1", "name": "Technical", "duration_minutes": 45,
                  "requisition_id": "r1", "round_number": 1, "default_interviewer_emails": []}],
            ],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h._select_role(DETECTION_ID, "r1", _action_payload("cal_intel_select_role"))
    # Role CAS set matched_requisition_id + advanced status; ui_state → round_select.
    det_updates = [w for w in fake.writes if w[0] == "calendar_event_detections" and w[1] == "update"]
    assert det_updates[0][2]["matched_requisition_id"] == "r1"
    assert det_updates[0][2]["detection_status"] == "awaiting_round"
    persisted = det_updates[-1][2]["detection_signals"]["_ui_state"]
    assert persisted["current_step"] == "round_select"
    assert persisted["selected_requisition_id"] == "r1"


async def test_select_role_cas_conflict_raises(captured_blocks):
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[_detection_row(status="notified")]],
            "requisitions": [
                [{"id": "r1", "role_title": "SWE", "created_by": PROFILE_ID}],
            ],
        },
        write_results={("calendar_event_detections", "update"): [[]]},  # CAS miss
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.DetectionAlreadyProcessedError):
            await h._select_role(DETECTION_ID, "r1", _action_payload("cal_intel_select_role"))


# ===========================================================================
# _select_round — round selection, CAS, ownership, missing round
# ===========================================================================


async def test_select_round_missing_round_id_prompts(captured_blocks):
    await h._select_round(DETECTION_ID, None, _action_payload("cal_intel_select_round"))
    assert "select a round first" in str(captured_blocks[-1])


async def test_select_round_deleted_round_raises(captured_blocks):
    det = _detection_row(status="awaiting_round", matched_requisition_id="r1")
    det["detection_signals"] = {"_ui_state": {"current_step": "round_select", "role_title": "SWE"}}
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[]],  # round lookup empty
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.RoundDeletedError):
            await h._select_round(DETECTION_ID, "rd1", _action_payload("cal_intel_select_round"))


async def test_select_round_foreign_round_raises(captured_blocks):
    det = _detection_row(status="awaiting_round", matched_requisition_id="r1")
    det["detection_signals"] = {"_ui_state": {"current_step": "round_select", "role_title": "SWE"}}
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[{"id": "rd1", "name": "Tech", "duration_minutes": 45, "requisition_id": "OTHER"}]],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.CalendarIntelligenceError):
            await h._select_round(DETECTION_ID, "rd1", _action_payload("cal_intel_select_round"))


async def test_select_round_advances_to_review(captured_blocks):
    det = _detection_row(status="awaiting_round", matched_requisition_id="r1")
    det["detection_signals"] = {
        "_ui_state": {"current_step": "round_select", "role_title": "SWE",
                      "round_candidates": [{"id": "rd1"}]}
    }
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[{"id": "rd1", "name": "Tech", "duration_minutes": 45, "requisition_id": "r1"}]],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h._select_round(DETECTION_ID, "rd1", _action_payload("cal_intel_select_round"))
    det_updates = [w for w in fake.writes if w[0] == "calendar_event_detections" and w[1] == "update"]
    assert det_updates[0][2]["detection_status"] == "awaiting_confirm"
    persisted = det_updates[-1][2]["detection_signals"]["_ui_state"]
    assert persisted["current_step"] == "review"
    assert persisted["selected_round_id"] == "rd1"


async def test_select_round_cas_conflict_raises(captured_blocks):
    det = _detection_row(status="awaiting_round", matched_requisition_id="r1")
    det["detection_signals"] = {"_ui_state": {"current_step": "round_select", "role_title": "SWE"}}
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[{"id": "rd1", "name": "Tech", "duration_minutes": 45, "requisition_id": "r1"}]],
        },
        write_results={("calendar_event_detections", "update"): [[]]},
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.DetectionAlreadyProcessedError):
            await h._select_round(DETECTION_ID, "rd1", _action_payload("cal_intel_select_round"))


async def test_select_round_terminal_raises(captured_blocks):
    fake = _FakeSupabase(
        selects={"calendar_event_detections": [[_detection_row(status="undone")]]}
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.DetectionAlreadyProcessedError):
            await h._select_round(DETECTION_ID, "rd1", _action_payload("cal_intel_select_round"))


# ===========================================================================
# _undo — confirmed-only guard + undo window
# ===========================================================================


async def test_undo_not_confirmed_raises(captured_blocks):
    fake = _FakeSupabase(
        selects={"calendar_event_detections": [[_detection_row(status="notified")]]}
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.DetectionAlreadyProcessedError):
            await h._undo(DETECTION_ID, _action_payload("cal_intel_undo"))


async def test_undo_window_expired_raises(captured_blocks):
    det = _detection_row(status="confirmed", undo_expires_at="2000-01-01T00:00:00+00:00")
    fake = _FakeSupabase(selects={"calendar_event_detections": [[det]]})
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.UndoExpiredError):
            await h._undo(DETECTION_ID, _action_payload("cal_intel_undo"))


# ===========================================================================
# handle_cal_intel_action — exception → error block mapping
# ===========================================================================


async def test_dispatch_maps_expired_to_error_block(captured_blocks):
    # _select_role raises DetectionExpiredError (detection not found) →
    # the dispatcher catches it and renders the "expired" error block.
    fake = _FakeSupabase(
        selects={
            # auth gate lookups
            "calendar_event_detections": [
                [{"profile_id": PROFILE_ID}],   # auth: owner lookup
                [],                              # _get_detection: not found → expired
            ],
            "slack_connections": [[{"profile_id": PROFILE_ID}]],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h.handle_cal_intel_action(
            "cal_intel_select_role",
            _action_payload("cal_intel_select_role", {"detection_id": DETECTION_ID, "requisition_id": "r1"}),
        )
    assert "expired" in str(captured_blocks[-1]).lower()


# ===========================================================================
# _select_candidate — disambiguation gate (never silently pick)
# ===========================================================================


async def test_select_candidate_single_option_no_op(captured_blocks):
    # One external attendee → nothing to disambiguate → silent return.
    det = _detection_row(status="awaiting_confirm")
    det["external_attendees"] = [{"email": "only@cand.com", "display_name": "Only"}]
    fake = _FakeSupabase(selects={"calendar_event_detections": [[det]]})
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h._select_candidate(DETECTION_ID, "only@cand.com", _action_payload("cal_intel_select_candidate"))
    assert captured_blocks == []


async def test_select_candidate_terminal_raises(captured_blocks):
    det = _detection_row(status="confirmed")
    det["external_attendees"] = [
        {"email": "a@cand.com", "display_name": "A"},
        {"email": "b@cand.com", "display_name": "B"},
    ]
    fake = _FakeSupabase(selects={"calendar_event_detections": [[det]]})
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        with pytest.raises(h.DetectionAlreadyProcessedError):
            await h._select_candidate(DETECTION_ID, "a@cand.com", _action_payload("cal_intel_select_candidate"))


async def test_select_candidate_no_round_selected_prompts(captured_blocks):
    # Two candidates → valid selection persisted, but no round chosen yet →
    # prompt to select a round first.
    det = _detection_row(status="awaiting_confirm")
    det["external_attendees"] = [
        {"email": "a@cand.com", "display_name": "A"},
        {"email": "b@cand.com", "display_name": "B"},
    ]
    det["detection_signals"] = {"_ui_state": {"current_step": "review", "selected_round_id": ""}}
    fake = _FakeSupabase(selects={"calendar_event_detections": [[det]]})
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h._select_candidate(DETECTION_ID, "a@cand.com", _action_payload("cal_intel_select_candidate"))
    # selected_candidate_email was persisted before the round check.
    det_updates = [w for w in fake.writes if w[0] == "calendar_event_detections" and w[1] == "update"]
    persisted = det_updates[-1][2]["detection_signals"]["_ui_state"]
    assert persisted["selected_candidate_email"] == "a@cand.com"
    assert "select a round first" in str(captured_blocks[-1])


async def test_select_candidate_renders_review(captured_blocks):
    det = _detection_row(status="awaiting_confirm", matched_requisition_id="r1")
    det["external_attendees"] = [
        {"email": "a@cand.com", "display_name": "A"},
        {"email": "b@cand.com", "display_name": "B"},
    ]
    det["detection_signals"] = {
        "_ui_state": {
            "current_step": "review", "selected_round_id": "rd1", "role_title": "SWE",
            "round_candidates": [{"id": "rd1"}],
        }
    }
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "rounds": [[{"id": "rd1", "name": "Tech", "duration_minutes": 45, "requisition_id": "r1"}]],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h._select_candidate(DETECTION_ID, "a@cand.com", _action_payload("cal_intel_select_candidate"))
    assert captured_blocks  # review rendered


# ===========================================================================
# _back_to_role / _back_to_detected — navigation pop
# ===========================================================================


async def test_back_to_role_no_history_falls_back_to_detected(captured_blocks):
    det = _detection_row(status="awaiting_round")
    det["detection_signals"] = {"_ui_state": {"current_step": "round_select", "state_stack": []}}
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det], [det]],  # _back_to_role + _back_to_detected each fetch
            "requisitions": [[]],  # _build_detected_step_blocks fetch (no reqs)
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h._back_to_role(DETECTION_ID, _action_payload("cal_intel_back_role"))
    # Fell through to _back_to_detected, which renders the detected step.
    assert captured_blocks


async def test_back_to_role_relists_roles(captured_blocks):
    det = _detection_row(status="awaiting_round")
    det["detection_signals"] = {
        "_ui_state": {"current_step": "round_select",
                      "state_stack": [{"step": "role_select"}]}
    }
    reqs = [{"id": "r1", "role_title": "SWE", "role_location": "Remote",
             "status": "open", "created_at": "2025-01-01"}]
    fake = _FakeSupabase(
        selects={
            "calendar_event_detections": [[det]],
            "requisitions": [list(reqs)],
        }
    )
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h._back_to_role(DETECTION_ID, _action_payload("cal_intel_back_role"))
    det_updates = [w for w in fake.writes if w[0] == "calendar_event_detections" and w[1] == "update"]
    persisted = det_updates[-1][2]["detection_signals"]["_ui_state"]
    assert persisted["current_step"] == "role_select"


# ===========================================================================
# handle_cal_intel_modal_submit
# ===========================================================================


async def test_modal_submit_disabled_flag_no_op(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "CALENDAR_INTELLIGENCE_ENABLED", False)
    called = []
    monkeypatch.setattr(h, "_select_role", AsyncMock(side_effect=lambda *a, **k: called.append(1)))
    with patch.object(h, "get_settings", return_value=settings):
        await h.handle_cal_intel_modal_submit({"view": {"callback_id": "cal_intel_modal_x"}})
    assert called == []


async def test_modal_submit_routes_to_select_role(monkeypatch):
    payload = {
        "view": {
            "callback_id": f"cal_intel_modal_{DETECTION_ID}",
            "state": {
                "values": {
                    "role_select_block": {
                        "role_select_action": {"selected_option": {"value": "r1"}}
                    }
                }
            },
        },
        "user": {"id": "slack-user-1"},
        "team": {"id": "T1"},
    }
    fake = _FakeSupabase(
        selects={
            # det lookup (channel/ts/profile), actor slack_conn, owner slack_conn
            "calendar_event_detections": [
                [{"slack_channel_id": "C1", "slack_message_ts": "1.2", "profile_id": PROFILE_ID}]
            ],
            "slack_connections": [
                [{"profile_id": PROFILE_ID}],          # actor auth
                [{"slack_team_id": "T1"}],             # team lookup
            ],
        }
    )
    select_calls = []

    async def _fake_select(detection_id, requisition_id, enriched_payload):
        select_calls.append((detection_id, requisition_id))

    monkeypatch.setattr(h, "_select_role", _fake_select)
    with patch.object(h, "get_supabase_admin_client", return_value=fake):
        await h.handle_cal_intel_modal_submit(payload)
    assert select_calls == [(DETECTION_ID, "r1")]
