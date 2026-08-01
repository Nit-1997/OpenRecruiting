"""BE-T6: behavioural coverage of untracked_capture_service.

Covers the auto-join preference resolution (incl. the missing-column org
fallback), binding materialization + race, candidate / candidate_round
create-or-reuse (incl. the pre-migration detection-scoped fallback), and the
full materialize/capture flow with its bot-link-failure and exception-cleanup
paths. Supabase is the table-routed queue recorder; insert_many and the
calendar_intelligence_service helpers are stubbed.
"""

import pytest

import app.services.untracked_capture_service as cap
from app.services.untracked_capture_service import (
    GENERIC_TEMPLATE_CONFIG,
    UntrackedCaptureResult,
    capture_untracked_interview,
    materialize_untracked_capture,
    resolve_or_materialize_binding,
    get_auto_join_untracked_preference,
    is_auto_join_untracked_enabled,
    is_untracked_capture_enabled,
    _candidate_email_from_detection,
    _candidate_name_from_detection,
    _is_unique_violation,
    _first_row,
)
from app.services.supabase import PostgrestError

ORG_ID = "org-1"


class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, fake, table):
        self._fake = fake
        self._table = table
        self._op = "select"
        self._payload = None

    def select(self, *a, **k):
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

    def eq(self, *a, **k):
        return self

    def neq(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    async def execute_async(self):
        key = (self._table, self._op)
        if self._op in ("insert", "update"):
            self._fake.writes.append((self._table, self._op, self._payload))
            if key in self._fake.raise_on:
                # one-shot raises so a retry/recheck can succeed
                exc = self._fake.raise_on.pop(key)
                raise exc
            row = dict(self._payload) if isinstance(self._payload, dict) else self._payload
            if isinstance(row, dict):
                row.setdefault("id", self._fake.insert_ids.get(self._table, f"{self._table}-id"))
            return _Resp([row] if isinstance(row, dict) else row)
        if key in self._fake.raise_on:
            exc = self._fake.raise_on.pop(key)
            raise exc
        queue = self._fake.selects.get(self._table, [])
        data = queue.pop(0) if queue else []
        return _Resp(data)


class _FakeSb:
    def __init__(self):
        self.selects: dict[str, list] = {}
        self.insert_ids: dict[str, str] = {}
        self.raise_on: dict[tuple, Exception] = {}
        self.writes: list[tuple] = []

    def table(self, name):
        return _Q(self, name)

    def writes_to(self, table, op):
        return [w for w in self.writes if w[0] == table and w[1] == op]


def _stub_insert_many(monkeypatch, fake):
    def _fake_im(client, table, data):
        class _IM:
            async def execute_async(self):
                fake.writes.append((table, "insert_many", data))
                return _Resp([dict(d) for d in data])
        return _IM()
    monkeypatch.setattr(cap, "insert_many", _fake_im)


def _stub_resolvers(monkeypatch, name="Alice", email="iv@x.com"):
    monkeypatch.setattr(cap, "resolve_candidate_name", lambda d, e: name)
    monkeypatch.setattr(cap, "resolve_interviewer_email", lambda *a, **k: email)


def _unique() -> PostgrestError:
    return PostgrestError("duplicate key value violates unique constraint", code="23505")


# --- helpers ---------------------------------------------------------------
def test_is_unique_violation():
    assert _is_unique_violation(Exception("duplicate key")) is True
    assert _is_unique_violation(Exception("unique constraint")) is True
    assert _is_unique_violation(Exception("other")) is False


def test_first_row():
    assert _first_row([{"a": 1}]) == {"a": 1}
    assert _first_row([]) is None
    assert _first_row({"a": 1}) == {"a": 1}
    assert _first_row(None) is None


def test_candidate_email_from_detection():
    det = {"external_attendees": [{"email": ""}, {"email": "Cand@X.com"}]}
    assert _candidate_email_from_detection(det) == "cand@x.com"
    assert _candidate_email_from_detection({}) == ""


def test_candidate_name_from_detection_resolver(monkeypatch):
    _stub_resolvers(monkeypatch, name="Resolved Name")
    det = {"external_attendees": [{"email": "c@x.com", "display_name": "Attendee"}]}
    assert _candidate_name_from_detection(det, "c@x.com") == "Resolved Name"


def test_candidate_name_from_detection_attendee_fallback(monkeypatch):
    monkeypatch.setattr(cap, "resolve_candidate_name", lambda d, e: None)
    det = {"external_attendees": [{"display_name": "Attendee Name"}]}
    assert _candidate_name_from_detection(det, "c@x.com") == "Attendee Name"


def test_candidate_name_from_detection_classification_fallback(monkeypatch):
    monkeypatch.setattr(cap, "resolve_candidate_name", lambda d, e: None)
    det = {"detection_signals": {"classification": {"candidate_name": "From Classifier"}}}
    assert _candidate_name_from_detection(det, "") == "From Classifier"


def test_candidate_name_from_detection_unknown():
    det = {}
    assert _candidate_name_from_detection(det, "") == "Unknown Candidate"


def test_is_missing_auto_join_column_error():
    err = Exception("column organizations.auto_join_untracked does not exist")
    assert cap._is_missing_auto_join_untracked_column_error(err) is True
    assert cap._is_missing_auto_join_untracked_column_error(Exception("other")) is False


# --- get_auto_join_untracked_preference -----------------------------------
@pytest.mark.asyncio
async def test_pref_missing_profile_id():
    enabled, source = await get_auto_join_untracked_preference(_FakeSb(), profile_id="")
    assert enabled is False and source == "missing_profile_id"


@pytest.mark.asyncio
async def test_pref_from_user_connection():
    fake = _FakeSb()
    fake.selects["user_connections"] = [[{"auto_join_untracked": True}]]
    enabled, source = await get_auto_join_untracked_preference(fake, profile_id="p1")
    assert enabled is True and source == "user_connection"


@pytest.mark.asyncio
async def test_pref_missing_user_connection():
    fake = _FakeSb()
    fake.selects["user_connections"] = [[]]
    enabled, source = await get_auto_join_untracked_preference(fake, profile_id="p1")
    assert enabled is False and source == "missing_user_connection"


@pytest.mark.asyncio
async def test_pref_column_error_org_fallback_enabled():
    fake = _FakeSb()
    fake.raise_on[("user_connections", "select")] = Exception(
        "column user_connections.auto_join_untracked does not exist")
    fake.selects["organizations"] = [[{"auto_join_untracked": True}]]
    enabled, source = await get_auto_join_untracked_preference(
        fake, profile_id="p1", organization_id=ORG_ID)
    assert enabled is True and source == "organization_fallback_enabled"


@pytest.mark.asyncio
async def test_pref_column_error_org_fallback_disabled():
    fake = _FakeSb()
    fake.raise_on[("user_connections", "select")] = Exception(
        "column auto_join_untracked does not exist")
    fake.selects["organizations"] = [[{"auto_join_untracked": False}]]
    enabled, source = await get_auto_join_untracked_preference(
        fake, profile_id="p1", organization_id=ORG_ID)
    assert enabled is False and source == "organization_fallback_disabled"


@pytest.mark.asyncio
async def test_pref_other_error_reraised():
    fake = _FakeSb()
    fake.raise_on[("user_connections", "select")] = RuntimeError("network")
    with pytest.raises(RuntimeError):
        await get_auto_join_untracked_preference(fake, profile_id="p1", organization_id=ORG_ID)


@pytest.mark.asyncio
async def test_is_auto_join_enabled_with_profile():
    fake = _FakeSb()
    fake.selects["user_connections"] = [[{"auto_join_untracked": True}]]
    assert await is_auto_join_untracked_enabled(fake, ORG_ID, profile_id="p1") is True


@pytest.mark.asyncio
async def test_is_auto_join_enabled_org_only():
    fake = _FakeSb()
    fake.selects["organizations"] = [[{"auto_join_untracked": True}]]
    assert await is_auto_join_untracked_enabled(fake, ORG_ID) is True


@pytest.mark.asyncio
async def test_is_auto_join_enabled_org_missing_row():
    fake = _FakeSb()
    fake.selects["organizations"] = [[]]
    assert await is_auto_join_untracked_enabled(fake, ORG_ID) is False


def test_is_untracked_capture_enabled():
    # default settings have the flag; just assert it returns a bool deterministically
    assert isinstance(is_untracked_capture_enabled(), bool)


# --- resolve_or_materialize_binding ---------------------------------------
@pytest.mark.asyncio
async def test_resolve_binding_returns_existing():
    fake = _FakeSb()
    fake.selects["org_generic_template_bindings"] = [[{
        "id": "b1", "organization_id": ORG_ID, "template_key": GENERIC_TEMPLATE_CONFIG["template_key"],
        "materialized_requisition_id": "req-g", "materialized_round_id": "round-g",
    }]]
    out = await resolve_or_materialize_binding(fake, ORG_ID)
    assert out["materialized_requisition_id"] == "req-g"


@pytest.mark.asyncio
async def test_resolve_binding_materializes_new(monkeypatch):
    fake = _FakeSb()
    _stub_insert_many(monkeypatch, fake)
    # _get_binding -> none (first call)
    fake.selects["org_generic_template_bindings"] = [[]]
    fake.insert_ids["requisitions"] = "new-req"
    fake.insert_ids["rounds"] = "new-round"
    fake.insert_ids["org_generic_template_bindings"] = "new-binding"
    out = await resolve_or_materialize_binding(fake, ORG_ID)
    assert out["materialized_requisition_id"] == "new-req"
    assert out["materialized_round_id"] == "new-round"
    # questions persisted via insert_many
    assert [w for w in fake.writes if w[0] == "feedback_questions" and w[1] == "insert_many"]


@pytest.mark.asyncio
async def test_resolve_binding_race_returns_existing_and_cleans_up(monkeypatch):
    fake = _FakeSb()
    _stub_insert_many(monkeypatch, fake)
    fake.selects["org_generic_template_bindings"] = [
        [],  # first _get_binding -> none -> materialize
        # after unique violation, _get_binding -> existing (the winner)
        [{"id": "winner", "materialized_requisition_id": "req-w", "materialized_round_id": "round-w"}],
    ]
    fake.insert_ids["requisitions"] = "loser-req"
    fake.insert_ids["rounds"] = "loser-round"
    fake.raise_on[("org_generic_template_bindings", "insert")] = _unique()
    out = await resolve_or_materialize_binding(fake, ORG_ID)
    assert out["id"] == "winner"
    # orphan req + round soft-deleted via cleanup
    assert fake.writes_to("requisitions", "update")
    assert fake.writes_to("rounds", "update")


@pytest.mark.asyncio
async def test_resolve_binding_insert_failure_raises(monkeypatch):
    fake = _FakeSb()
    _stub_insert_many(monkeypatch, fake)
    fake.selects["org_generic_template_bindings"] = [[]]
    # requisition insert returns empty -> RuntimeError
    fake.raise_on[("requisitions", "insert")] = RuntimeError("insert failed hard")
    with pytest.raises(RuntimeError):
        await resolve_or_materialize_binding(fake, ORG_ID)


# --- _create_or_reuse_generic_candidate -----------------------------------
@pytest.mark.asyncio
async def test_create_candidate_reuses_existing(monkeypatch):
    _stub_resolvers(monkeypatch)
    fake = _FakeSb()
    fake.selects["candidates"] = [[{"id": "c-existing", "name": "Alice", "email": "a@x.com"}]]
    det = {"id": "det-1", "external_attendees": [{"email": "a@x.com"}]}
    row, created = await cap._create_or_reuse_generic_candidate(fake, "req-g", det)
    assert row["id"] == "c-existing" and created is False


@pytest.mark.asyncio
async def test_create_candidate_creates_new(monkeypatch):
    _stub_resolvers(monkeypatch)
    fake = _FakeSb()
    fake.selects["candidates"] = [[]]  # not existing
    fake.insert_ids["candidates"] = "c-new"
    det = {"id": "det-1", "external_attendees": [{"email": "new@x.com"}]}
    row, created = await cap._create_or_reuse_generic_candidate(fake, "req-g", det)
    assert row["id"] == "c-new" and created is True


@pytest.mark.asyncio
async def test_create_candidate_synthetic_email_when_none(monkeypatch):
    _stub_resolvers(monkeypatch)
    fake = _FakeSb()
    fake.selects["candidates"] = [[]]
    fake.insert_ids["candidates"] = "c-new"
    det = {"id": "det-7", "external_attendees": []}
    row, created = await cap._create_or_reuse_generic_candidate(fake, "req-g", det)
    ins = fake.writes_to("candidates", "insert")[0][2]
    assert ins["email"] == "unknown+det-7@untracked.local"


@pytest.mark.asyncio
async def test_create_candidate_unique_violation_rechecks(monkeypatch):
    _stub_resolvers(monkeypatch)
    fake = _FakeSb()
    # existing lookup none, insert raises 23505, recheck finds it
    fake.selects["candidates"] = [[], [{"id": "c-raced", "name": "Alice", "email": "a@x.com"}]]
    fake.raise_on[("candidates", "insert")] = _unique()
    det = {"id": "det-1", "external_attendees": [{"email": "a@x.com"}]}
    row, created = await cap._create_or_reuse_generic_candidate(fake, "req-g", det)
    assert row["id"] == "c-raced" and created is False


# --- _create_or_reuse_generic_candidate_round -----------------------------
@pytest.mark.asyncio
async def test_create_round_happy(monkeypatch):
    _stub_resolvers(monkeypatch)
    fake = _FakeSb()
    fake.insert_ids["candidate_rounds"] = "cr-new"
    det = {"id": "det-1", "meeting_url": "https://m", "event_start": "2025-01-01"}
    cr_id, created = await cap._create_or_reuse_generic_candidate_round(fake, "c1", "round-g", det)
    assert cr_id == "cr-new" and created is True


@pytest.mark.asyncio
async def test_create_round_unique_reuses_same_detection(monkeypatch):
    _stub_resolvers(monkeypatch)
    fake = _FakeSb()
    fake.raise_on[("candidate_rounds", "insert")] = _unique()
    # same-detection lookup finds the existing round
    fake.selects["candidate_rounds"] = [
        [{"id": "cr-existing", "origin_detection_id": "det-1"}],
    ]
    det = {"id": "det-1", "meeting_url": "https://m", "event_start": "2025-01-01"}
    cr_id, created = await cap._create_or_reuse_generic_candidate_round(fake, "c1", "round-g", det)
    assert cr_id == "cr-existing" and created is False


@pytest.mark.asyncio
async def test_create_round_premigration_fallback_synthetic_candidate(monkeypatch):
    _stub_resolvers(monkeypatch)
    fake = _FakeSb()
    fake.raise_on[("candidate_rounds", "insert")] = _unique()
    fake.selects["candidate_rounds"] = [
        [],  # same-detection lookup -> none
        # global (candidate,round) lookup -> exists but a DIFFERENT detection
        [{"id": "cr-other", "origin_detection_id": "det-OTHER"}],
    ]
    # candidate lookup for fallback synthetic candidate
    fake.selects["candidates"] = [[{"id": "c1", "requisition_id": "req-g", "name": "Alice"}]]
    fake.insert_ids["candidates"] = "synthetic-cand"
    fake.insert_ids["candidate_rounds"] = "cr-fallback"
    det = {"id": "det-1", "meeting_url": "https://m", "event_start": "2025-01-01"}
    cr_id, created = await cap._create_or_reuse_generic_candidate_round(fake, "c1", "round-g", det)
    assert cr_id == "cr-fallback" and created is True
    # a synthetic detection-scoped candidate was created
    cand_ins = fake.writes_to("candidates", "insert")
    assert any(w[2]["email"] == "unknown+det-1@untracked.local" for w in cand_ins)


# --- materialize_untracked_capture (full flow) ----------------------------
def _capture_binding_selects():
    return {
        "org_generic_template_bindings": [[{
            "id": "b1", "organization_id": ORG_ID,
            "template_key": GENERIC_TEMPLATE_CONFIG["template_key"],
            "materialized_requisition_id": "req-g", "materialized_round_id": "round-g",
        }]],
        "candidates": [[]],  # candidate not existing -> create
        "candidate_rounds": [],  # insert succeeds (no queue needed)
    }


@pytest.mark.asyncio
async def test_materialize_full_flow_confirmed(monkeypatch):
    _stub_resolvers(monkeypatch)
    fake = _FakeSb()
    fake.selects = _capture_binding_selects()
    fake.insert_ids["candidates"] = "cand-new"
    fake.insert_ids["candidate_rounds"] = "cr-new"

    bot_calls = []

    async def _bot_linker(detection_id, candidate_round_id, sb):
        bot_calls.append((detection_id, candidate_round_id))
        return True

    det = {
        "id": "det-1", "organization_id": ORG_ID, "event_title": "Interview",
        "external_attendees": [{"email": "cand@x.com"}], "internal_attendees": [],
        "meeting_url": "https://m", "event_start": "2025-01-01",
    }
    out = await capture_untracked_interview(fake, det, _bot_linker)
    assert isinstance(out, UntrackedCaptureResult)
    assert out.candidate_round_id == "cr-new"
    assert bot_calls == [("det-1", "cr-new")]
    # detection finalized (confirmed) since capture_untracked_interview sets it
    det_upd = fake.writes_to("calendar_event_detections", "update")
    assert det_upd and det_upd[0][2]["detection_status"] == "confirmed"


@pytest.mark.asyncio
async def test_materialize_preconfirm_does_not_finalize(monkeypatch):
    _stub_resolvers(monkeypatch)
    fake = _FakeSb()
    fake.selects = _capture_binding_selects()
    fake.insert_ids["candidates"] = "cand-new"
    fake.insert_ids["candidate_rounds"] = "cr-new"

    async def _bot_linker(*a):
        return True

    det = {
        "id": "det-1", "organization_id": ORG_ID, "event_title": "Interview",
        "external_attendees": [{"email": "cand@x.com"}], "internal_attendees": [],
        "meeting_url": "https://m", "event_start": "2025-01-01",
    }
    out = await materialize_untracked_capture(fake, det, _bot_linker, capture_mode="preconfirm")
    assert out is not None
    det_upd = fake.writes_to("calendar_event_detections", "update")
    signals = det_upd[0][2]["detection_signals"]
    assert signals["untracked_capture_mode"] == "preconfirm"
    assert "detection_status" not in det_upd[0][2]


@pytest.mark.asyncio
async def test_materialize_bot_link_failure_cancels_round(monkeypatch):
    _stub_resolvers(monkeypatch)
    fake = _FakeSb()
    fake.selects = _capture_binding_selects()
    fake.insert_ids["candidates"] = "cand-new"
    fake.insert_ids["candidate_rounds"] = "cr-new"

    async def _bot_linker(*a):
        return False

    det = {
        "id": "det-1", "organization_id": ORG_ID, "event_title": "Interview",
        "external_attendees": [{"email": "cand@x.com"}], "internal_attendees": [],
        "meeting_url": "https://m", "event_start": "2025-01-01",
    }
    out = await capture_untracked_interview(fake, det, _bot_linker)
    assert out is None
    cr_upd = fake.writes_to("candidate_rounds", "update")
    assert any(w[2].get("status") == "cancelled" for w in cr_upd)


@pytest.mark.asyncio
async def test_materialize_exception_cancels_created_round(monkeypatch):
    _stub_resolvers(monkeypatch)
    fake = _FakeSb()
    fake.selects = _capture_binding_selects()
    fake.insert_ids["candidates"] = "cand-new"
    fake.insert_ids["candidate_rounds"] = "cr-new"

    async def _bot_linker(*a):
        raise RuntimeError("bot deploy exploded")

    det = {
        "id": "det-1", "organization_id": ORG_ID, "event_title": "Interview",
        "external_attendees": [{"email": "cand@x.com"}], "internal_attendees": [],
        "meeting_url": "https://m", "event_start": "2025-01-01",
    }
    out = await capture_untracked_interview(fake, det, _bot_linker)
    assert out is None
    # the created round (created_round=True) is cancelled in the except handler
    cr_upd = fake.writes_to("candidate_rounds", "update")
    assert any(w[2].get("status") == "cancelled" for w in cr_upd)


@pytest.mark.asyncio
async def test_materialize_reused_round_skips_bot_deploy(monkeypatch):
    _stub_resolvers(monkeypatch)
    fake = _FakeSb()
    fake.selects = _capture_binding_selects()
    fake.insert_ids["candidates"] = "cand-new"
    # candidate_round insert raises 23505 then same-detection lookup reuses
    fake.raise_on[("candidate_rounds", "insert")] = _unique()
    fake.selects["candidate_rounds"] = [
        [{"id": "cr-reused", "origin_detection_id": "det-1"}],
    ]

    bot_calls = []

    async def _bot_linker(*a):
        bot_calls.append(a)
        return True

    det = {
        "id": "det-1", "organization_id": ORG_ID, "event_title": "Interview",
        "external_attendees": [{"email": "cand@x.com"}], "internal_attendees": [],
        "meeting_url": "https://m", "event_start": "2025-01-01",
    }
    out = await materialize_untracked_capture(fake, det, _bot_linker)
    assert out.candidate_round_id == "cr-reused"
    # reused round -> bot deploy is skipped
    assert bot_calls == []
