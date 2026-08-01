"""BE-S5: RequisitionService correctness + dedup coverage.

Two findings under test:
  1. reorder_rounds must be ATOMIC — a single SECURITY DEFINER RPC
     (reorder_requisition_rounds), NOT the old two-phase 2N table updates that
     could leave rounds with negative round_number on a mid-sequence crash.
  2. create_interview_plan / update_interview_plan must share one
     question-persistence helper (no behavioural drift between the two paths).
"""
import pytest

from app.api.v2.core.exceptions import NotFoundError, ValidationError
from app.models.requisitions import (
    InterviewPlanCreate,
    RoundOrderItem,
    RoundReorderRequest,
)
from app.services.requisition_service import RequisitionService
from app.services.supabase import RpcError


# ---------------------------------------------------------------------------
# Minimal fake Supabase client: records rpc() calls; table() ops are no-ops
# except for the round-membership read reorder_rounds performs up front.
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, table, rows):
        self._table = table
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def is_null(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def single(self, *a, **k):
        return self

    async def execute_async(self):
        if self._table == "requisitions":
            return _FakeResponse({"id": "req-1"})
        if self._table == "rounds":
            return _FakeResponse([{"id": rid} for rid in self._rows["rounds"]])
        return _FakeResponse([])


class _FakeSupabase:
    def __init__(self, round_ids):
        self._round_ids = round_ids
        self.rpc_calls: list[tuple[str, dict]] = []
        self.table_updates: list[str] = []
        self.rpc_error: RpcError | None = None

    def table(self, name):
        return _FakeQuery(name, {"rounds": self._round_ids})

    async def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        if self.rpc_error is not None:
            raise self.rpc_error
        return _FakeResponse({"message": "Rounds reordered successfully"})


@pytest.mark.asyncio
async def test_reorder_rounds_uses_single_atomic_rpc():
    """The service must reorder via ONE rpc call passing the ordered id array,
    never the old per-round two-phase table updates."""
    fake = _FakeSupabase(round_ids=["r-a", "r-b", "r-c"])
    svc = RequisitionService(fake)

    # Caller asks for order b(1), c(2), a(3).
    req = RoundReorderRequest(
        round_orders=[
            RoundOrderItem(round_id="11111111-1111-1111-1111-111111111111", round_number=2),
            RoundOrderItem(round_id="22222222-2222-2222-2222-222222222222", round_number=1),
            RoundOrderItem(round_id="33333333-3333-3333-3333-333333333333", round_number=3),
        ]
    )
    # Make membership check pass by aligning fake round ids with the payload.
    fake._round_ids = [str(o.round_id) for o in req.round_orders]

    result = await svc.reorder_rounds("req-1", req)

    assert len(fake.rpc_calls) == 1, "must be exactly ONE atomic RPC call"
    name, params = fake.rpc_calls[0]
    assert name == "reorder_requisition_rounds"
    assert params["p_requisition_id"] == "req-1"
    # ids ordered by requested round_number -> position 1..N
    assert params["p_ordered_round_ids"] == [
        "22222222-2222-2222-2222-222222222222",  # round_number 1
        "11111111-1111-1111-1111-111111111111",  # round_number 2
        "33333333-3333-3333-3333-333333333333",  # round_number 3
    ]
    assert result["message"]


@pytest.mark.asyncio
async def test_reorder_rounds_maps_not_found_rpc_error():
    """A P0002 from the RPC maps to a v2 NotFoundError (404)."""
    fake = _FakeSupabase(round_ids=["33333333-3333-3333-3333-333333333333"])
    fake.rpc_error = RpcError("Requisition not found", code="P0002")
    svc = RequisitionService(fake)
    req = RoundReorderRequest(
        round_orders=[
            RoundOrderItem(round_id="33333333-3333-3333-3333-333333333333", round_number=1),
        ]
    )
    with pytest.raises(NotFoundError):
        await svc.reorder_rounds("req-1", req)


@pytest.mark.asyncio
async def test_reorder_rounds_rejects_unknown_round_before_rpc():
    """A round id not in the requisition is rejected before any RPC call."""
    fake = _FakeSupabase(round_ids=["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"])
    svc = RequisitionService(fake)
    req = RoundReorderRequest(
        round_orders=[
            RoundOrderItem(round_id="33333333-3333-3333-3333-333333333333", round_number=1),
        ]
    )
    with pytest.raises(Exception):
        await svc.reorder_rounds("req-1", req)
    assert fake.rpc_calls == [], "must not call the RPC when membership fails"


# ---------------------------------------------------------------------------
# Dedup: both plan methods route question persistence through one helper.
# ---------------------------------------------------------------------------
def test_persist_round_questions_helper_exists():
    """The shared helper both plan methods use must exist."""
    assert hasattr(RequisitionService, "_persist_round_questions")


# ===========================================================================
# BE-T6: behavioural coverage of RequisitionService CRUD + soft-delete paths.
#
# A queue-based table-routed fake supabase: each table holds an ordered queue
# of responses, and every read/write pops the next one. Writes are recorded.
# This mirrors the recorder used by the untracked-conflict tests but supports
# the much wider read/write surface RequisitionService exercises.
# ===========================================================================
import asyncio as _asyncio

import pytest as _pytest
from fastapi import HTTPException

import app.services.requisition_service as rs
from app.models.requisitions import (
    RequisitionCreate,
    RequisitionUpdate,
    IntakeUpdate,
    InterviewPlanCreate,
    RoundCreate,
    RoundUpdate,
    FeedbackQuestionCreate,
    FeedbackQuestionUpdate,
)


class _Resp:
    def __init__(self, data, count=0):
        self.data = data
        self._count = count


class _Q:
    """Fluent no-op query that pops a queued response on execute_async().

    Writes (insert/update/upsert) are logged on the parent fake and return
    the queued response if one is set, else an echo of the payload.
    """

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

    def upsert(self, payload, **k):
        self._op = "upsert"
        self._payload = payload
        return self

    def eq(self, *a, **k):
        return self

    def neq(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def is_null(self, *a, **k):
        return self

    def not_null(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def offset(self, *a, **k):
        return self

    def single(self, *a, **k):
        return self

    def _pop(self):
        queue = self._fake.selects.get(self._table)
        if queue:
            return queue.pop(0)
        return self._fake.default_select.get(self._table, [])

    async def execute_async(self):
        if self._op in ("insert", "update", "upsert"):
            self._fake.writes.append((self._table, self._op, self._payload))
            key = (self._table, self._op)
            if key in self._fake.raise_on:
                raise self._fake.raise_on[key]
            if self._table in self._fake.writes_return:
                ret = self._fake.writes_return[self._table]
                ret = ret.pop(0) if isinstance(ret, list) and ret and isinstance(ret[0], (list, dict)) else ret
                return _Resp(ret)
            # default echo: list with payload (+id)
            row = dict(self._payload) if isinstance(self._payload, dict) else self._payload
            if isinstance(row, dict):
                row.setdefault("id", self._fake.insert_ids.get(self._table, f"{self._table}-id"))
            return _Resp([row] if isinstance(row, dict) else row)
        return _Resp(self._pop())

    async def count_async(self):
        return self._fake.counts.get(self._table, 0)


class _FakeSb:
    def __init__(self):
        self.selects: dict[str, list] = {}
        self.default_select: dict[str, list] = {}
        self.writes_return: dict[str, object] = {}
        self.counts: dict[str, int] = {}
        self.insert_ids: dict[str, str] = {}
        self.raise_on: dict[tuple, Exception] = {}
        self.writes: list[tuple] = []
        self.rpc_calls: list[tuple] = []
        self.rpc_return = _Resp({"message": "ok"})

    def table(self, name):
        return _Q(self, name)

    async def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return self.rpc_return

    def writes_to(self, table, op):
        return [w for w in self.writes if w[0] == table and w[1] == op]


def _stub_insert_many(monkeypatch, fake):
    """Route insert_many through the same write-recorder so question/round
    bulk inserts are observable and echo back rows with ids."""
    def _fake_insert_many(client, table, data):
        class _IM:
            async def execute_async(self):
                fake.writes.append((table, "insert_many", data))
                rows = [dict(d) for d in data]
                for i, r in enumerate(rows):
                    r.setdefault("id", f"{table}-{i}")
                return _Resp(rows)
        return _IM()
    monkeypatch.setattr(rs, "insert_many", _fake_insert_many)


# --- get_requisition -------------------------------------------------------
@_pytest.mark.asyncio
async def test_get_requisition_attaches_org_flag_and_builds_response():
    fake = _FakeSb()
    fake.selects["requisitions"] = [
        {"id": "req-1", "organization_id": "org-1", "role_title": "Eng",
         "experience_min_years": 3, "experience_max_years": 5, "must_have_skills": None},
    ]
    fake.selects["organizations"] = [[{"auto_join_untracked": True}]]
    svc = RequisitionService(fake)
    out = await svc.get_requisition("req-1", org_id="org-1")
    assert out["experience_display"] == "3-5 years"
    assert out["must_have_skills"] == []  # None coerced to []
    assert out["auto_join_untracked"] is True


@_pytest.mark.asyncio
async def test_get_requisition_404_when_missing():
    fake = _FakeSb()
    fake.selects["requisitions"] = [None]
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.get_requisition("missing")
    assert ei.value.status_code == 404


@_pytest.mark.asyncio
async def test_attach_org_flag_false_when_org_row_absent():
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "r", "organization_id": "org-x"}]
    fake.selects["organizations"] = [[]]
    svc = RequisitionService(fake)
    out = await svc.get_requisition("r")
    assert out["auto_join_untracked"] is False


# --- list_requisitions -----------------------------------------------------
@_pytest.mark.asyncio
async def test_list_requisitions_returns_built_rows_and_count():
    fake = _FakeSb()
    fake.selects["requisitions"] = [
        [{"id": "a", "organization_id": "org-1", "experience_min_years": 2, "experience_max_years": None}],
    ]
    fake.counts["requisitions"] = 7
    svc = RequisitionService(fake)
    rows, total = await svc.list_requisitions("org-1", page=1, page_size=25)
    assert total == 7
    assert rows[0]["experience_display"] == "2+ years"


@_pytest.mark.asyncio
async def test_list_requisitions_include_deleted_branch():
    fake = _FakeSb()
    fake.selects["requisitions"] = [[]]
    fake.counts["requisitions"] = 0
    svc = RequisitionService(fake)
    rows, total = await svc.list_requisitions("org-1", include_deleted=True)
    assert rows == [] and total == 0


# --- get_requisition_with_plan / get_interview_plan ------------------------
@_pytest.mark.asyncio
async def test_get_requisition_with_plan_builds_rounds_and_questions():
    fake = _FakeSb()
    # asyncio.gather order: req single, then rounds list
    fake.selects["requisitions"] = [{"id": "req-1", "organization_id": "org-1"}]
    fake.selects["rounds"] = [
        [
            {"id": "r1", "round_number": 2, "duration_minutes": 30},
            {"id": "r2", "round_number": 1, "duration_minutes": 45},
        ],
    ]
    fake.selects["feedback_questions"] = [
        [
            {"id": "q1", "round_id": "r2", "question_number": 1},
            {"id": "q2", "round_id": "r1", "question_number": 1},
        ],
    ]
    fake.selects["organizations"] = [[{"auto_join_untracked": False}]]
    svc = RequisitionService(fake)
    out = await svc.get_requisition_with_plan("req-1", org_id="org-1")
    plan = out["plan"]
    assert plan["total_rounds"] == 2
    assert plan["total_duration_minutes"] == 75
    # rounds sorted by round_number -> r2 (1) first
    assert plan["rounds"][0]["id"] == "r2"
    assert plan["rounds"][0]["feedback_questions"][0]["id"] == "q1"


@_pytest.mark.asyncio
async def test_get_requisition_with_plan_no_rounds_yields_null_plan():
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "req-1", "organization_id": "org-1"}]
    fake.selects["rounds"] = [[]]
    fake.selects["organizations"] = [[{"auto_join_untracked": False}]]
    svc = RequisitionService(fake)
    out = await svc.get_requisition_with_plan("req-1")
    assert out["plan"] is None


@_pytest.mark.asyncio
async def test_get_interview_plan_404_when_no_rounds():
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "req-1"}]
    fake.selects["rounds"] = [[]]
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.get_interview_plan("req-1")
    assert ei.value.status_code == 404


@_pytest.mark.asyncio
async def test_get_interview_plan_renumbers_and_attaches_template():
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "req-1"}]
    fake.selects["rounds"] = [
        [
            {"id": "r1", "round_number": 5, "duration_minutes": 30, "assessment_template_id": "tmpl-1"},
            {"id": "r2", "round_number": 9, "duration_minutes": 45},
        ],
    ]
    fake.selects["feedback_questions"] = [[]]
    fake.selects["assessment_templates"] = [[{"id": "tmpl-1", "name": "T"}]]
    svc = RequisitionService(fake)
    out = await svc.get_interview_plan("req-1")
    # round_number is renumbered 1..N by position
    assert out["rounds"][0]["round_number"] == 1
    assert out["rounds"][1]["round_number"] == 2
    assert out["rounds"][0]["assessment_template"]["name"] == "T"
    assert out["total_duration_minutes"] == 75


# --- create / update requisition ------------------------------------------
@_pytest.mark.asyncio
async def test_create_requisition_returns_built_response():
    fake = _FakeSb()
    fake.writes_return["requisitions"] = [
        {"id": "new", "organization_id": "org-1", "role_title": "Eng",
         "experience_min_years": 0, "experience_max_years": None, "status": "intake_pending"},
    ]
    svc = RequisitionService(fake)
    data = RequisitionCreate(role_title="Eng", role_location="Remote")
    out = await svc.create_requisition("org-1", data, created_by="user-1")
    assert out["status"] == "intake_pending"
    assert out["experience_display"] == "0+ years"


@_pytest.mark.asyncio
async def test_create_requisition_500_on_empty_insert():
    fake = _FakeSb()
    fake.writes_return["requisitions"] = []
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.create_requisition("org-1", RequisitionCreate(role_title="E", role_location="R"), "u")
    assert ei.value.status_code == 500


@_pytest.mark.asyncio
async def test_update_requisition_no_fields_returns_existing_without_write():
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "req-1", "experience_min_years": 1, "experience_max_years": 1}]
    svc = RequisitionService(fake)
    out = await svc.update_requisition("req-1", RequisitionUpdate())
    assert out["experience_display"] == "1 years"
    assert fake.writes_to("requisitions", "update") == []


@_pytest.mark.asyncio
async def test_update_requisition_applies_fields():
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "req-1"}]
    fake.writes_return["requisitions"] = [{"id": "req-1", "role_title": "New", "experience_min_years": 4, "experience_max_years": 4}]
    svc = RequisitionService(fake)
    out = await svc.update_requisition("req-1", RequisitionUpdate(role_title="New"))
    assert out["role_title"] == "New"
    upd = fake.writes_to("requisitions", "update")
    assert upd[0][2] == {"role_title": "New"}


@_pytest.mark.asyncio
async def test_update_requisition_404():
    fake = _FakeSb()
    fake.selects["requisitions"] = [None]
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.update_requisition("x", RequisitionUpdate(role_title="N"))
    assert ei.value.status_code == 404


@_pytest.mark.asyncio
async def test_update_intake_applies_skills():
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "req-1"}]
    fake.writes_return["requisitions"] = [{"id": "req-1", "must_have_skills": ["Py"]}]
    svc = RequisitionService(fake)
    out = await svc.update_intake("req-1", IntakeUpdate(must_have_skills=["Py"], intake_notes="n"))
    assert out["must_have_skills"] == ["Py"]
    payload = fake.writes_to("requisitions", "update")[0][2]
    assert payload["must_have_skills"] == ["Py"]
    assert payload["intake_notes"] == "n"


@_pytest.mark.asyncio
async def test_update_intake_noop_returns_existing():
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "req-1", "experience_min_years": 0, "experience_max_years": None}]
    svc = RequisitionService(fake)
    out = await svc.update_intake("req-1", IntakeUpdate())
    assert out["id"] == "req-1"
    assert fake.writes_to("requisitions", "update") == []


# --- update_status (incl. planned -> publish_event) ------------------------
@_pytest.mark.asyncio
async def test_update_status_rejects_disallowed():
    fake = _FakeSb()
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.update_status("req-1", "bogus", allowed_statuses=["planned", "active"])
    assert ei.value.status_code == 400


@_pytest.mark.asyncio
async def test_update_status_planned_publishes_event(monkeypatch):
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "req-1", "organization_id": "org-1"}]
    fake.writes_return["requisitions"] = [{"id": "req-1", "organization_id": "org-1", "status": "planned"}]
    published = []

    async def _pub(event, payload):
        published.append((event, payload))

    import app.services.sqs_publisher as sqs
    monkeypatch.setattr(sqs, "publish_event", _pub)
    svc = RequisitionService(fake)
    out = await svc.update_status("req-1", "planned")
    assert out["status"] == "planned"
    assert published[0][0] == "intake_complete"
    assert published[0][1]["requisition_id"] == "req-1"


@_pytest.mark.asyncio
async def test_update_status_planned_swallows_publish_error(monkeypatch):
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "req-1", "organization_id": "org-1"}]
    fake.writes_return["requisitions"] = [{"id": "req-1", "organization_id": "org-1", "status": "planned"}]

    async def _boom(*a, **k):
        raise RuntimeError("sqs down")

    import app.services.sqs_publisher as sqs
    monkeypatch.setattr(sqs, "publish_event", _boom)
    svc = RequisitionService(fake)
    out = await svc.update_status("req-1", "planned")  # must not raise
    assert out["status"] == "planned"


# --- get_intake_status -----------------------------------------------------
@_pytest.mark.asyncio
async def test_get_intake_status_shapes_response():
    fake = _FakeSb()
    fake.selects["requisitions"] = [{
        "id": "req-1",
        "intake_voice_session_status": "completed",
        "intake_processing_status": "done",
        "intake_summary": "sum",
        "intake_transcript": "blah",
    }]
    svc = RequisitionService(fake)
    out = await svc.get_intake_status("req-1")
    assert out["has_transcript"] is True
    assert out["intake_summary"] == "sum"


# --- create_intake_call_session -------------------------------------------
@_pytest.mark.asyncio
async def test_create_intake_call_session_rejects_active():
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "req-1", "status": "active"}]
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.create_intake_call_session("req-1")
    assert ei.value.status_code == 400


@_pytest.mark.asyncio
async def test_create_intake_call_session_resets_and_returns_token():
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "req-1", "status": "intake_pending"}]
    # delete_rounds_cascade: rounds select -> none
    fake.selects["rounds"] = [[]]
    fake.writes_return["requisitions"] = [{"id": "req-1"}]
    svc = RequisitionService(fake)
    out = await svc.create_intake_call_session("req-1")
    assert out["requisition_id"] == "req-1"
    assert out["session_token"]
    upd = fake.writes_to("requisitions", "update")[0][2]
    assert upd["intake_voice_session_status"] == "pending"


# --- soft_delete / restore -------------------------------------------------
@_pytest.mark.asyncio
async def test_soft_delete_requisition_cascades():
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "req-1", "deleted_at": None}]
    fake.selects["rounds"] = [[{"id": "r1"}, {"id": "r2"}]]
    svc = RequisitionService(fake)
    out = await svc.soft_delete_requisition("req-1")
    assert out["id"] == "req-1"
    # feedback_questions soft-deleted per round (2), rounds + candidates + req
    assert len(fake.writes_to("feedback_questions", "update")) == 2
    assert fake.writes_to("rounds", "update")
    assert fake.writes_to("candidates", "update")
    assert fake.writes_to("requisitions", "update")


@_pytest.mark.asyncio
async def test_soft_delete_already_deleted_400():
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "req-1", "deleted_at": "2025-01-01"}]
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.soft_delete_requisition("req-1")
    assert ei.value.status_code == 400


@_pytest.mark.asyncio
async def test_soft_delete_404():
    fake = _FakeSb()
    fake.selects["requisitions"] = [None]
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.soft_delete_requisition("x")
    assert ei.value.status_code == 404


@_pytest.mark.asyncio
async def test_restore_requisition_restores_questions():
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "req-1", "deleted_at": "2025-01-01"}]
    # restore reads rounds AFTER un-deleting; one round so questions restored
    fake.selects["rounds"] = [[{"id": "r1"}]]
    svc = RequisitionService(fake)
    out = await svc.restore_requisition("req-1")
    assert out["id"] == "req-1"
    assert fake.writes_to("feedback_questions", "update")


@_pytest.mark.asyncio
async def test_restore_not_deleted_400():
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "req-1", "deleted_at": None}]
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.restore_requisition("req-1")
    assert ei.value.status_code == 400


# --- create_interview_plan -------------------------------------------------
@_pytest.mark.asyncio
async def test_create_interview_plan_inserts_rounds_and_questions(monkeypatch):
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "req-1", "status": "intake_pending"}]
    fake.selects["rounds"] = [[]]  # no existing rounds
    fake.writes_return["rounds"] = {"id": "round-x", "round_number": 1, "duration_minutes": 45}
    _stub_insert_many(monkeypatch, fake)
    svc = RequisitionService(fake)
    plan = InterviewPlanCreate(rounds=[{
        "name": "Tech", "duration_minutes": 45,
        "feedback_questions": [{"heading": "Q1"}, {"heading": "Q2"}],
    }])
    out = await svc.create_interview_plan("req-1", plan)
    assert out["total_rounds"] == 1
    assert out["total_duration_minutes"] == 45
    assert out["rounds"][0]["feedback_questions"][0]["question_number"] == 1
    # questions persisted via insert_many helper
    im = [w for w in fake.writes if w[1] == "insert_many" and w[0] == "feedback_questions"]
    assert im and len(im[0][2]) == 2


@_pytest.mark.asyncio
async def test_create_interview_plan_rejects_existing_plan():
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "req-1", "status": "intake_pending"}]
    fake.selects["rounds"] = [[{"id": "existing"}]]
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.create_interview_plan("req-1", InterviewPlanCreate(rounds=[]))
    assert ei.value.status_code == 400


@_pytest.mark.asyncio
async def test_create_interview_plan_404_missing_req():
    fake = _FakeSb()
    fake.selects["requisitions"] = [None]
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.create_interview_plan("x", InterviewPlanCreate(rounds=[]))
    assert ei.value.status_code == 404


# --- update_interview_plan -------------------------------------------------
@_pytest.mark.asyncio
async def test_update_interview_plan_updates_existing_and_adds_new(monkeypatch):
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "req-1"}]
    # existing rounds: round_number 1 exists, 2 will be added, an old 3 removed
    fake.selects["rounds"] = [
        [{"id": "r1", "round_number": 1, "name": "Old1"},
         {"id": "r3", "round_number": 3, "name": "ToDelete"}],
        # re-read of updated round 1 (single)
        {"id": "r1", "round_number": 1, "duration_minutes": 30},
    ]
    fake.selects["candidates"] = [[{"id": "cand-1"}]]
    fake.writes_return["rounds"] = {"id": "r2-new", "round_number": 2, "duration_minutes": 45}
    _stub_insert_many(monkeypatch, fake)
    svc = RequisitionService(fake)
    plan = InterviewPlanCreate(rounds=[
        {"name": "New1", "duration_minutes": 30, "feedback_questions": [{"heading": "A"}]},
        {"name": "New2", "duration_minutes": 45, "feedback_questions": []},
    ])
    out = await svc.update_interview_plan("req-1", plan)
    assert out["total_rounds"] == 2
    assert out["total_duration_minutes"] == 75
    # existing round 1 updated; new round 2 inserted; old round 3 soft-deleted
    assert fake.writes_to("rounds", "update")
    assert fake.writes_to("rounds", "insert")
    # candidate_rounds created for the new round via insert_many
    assert [w for w in fake.writes if w[0] == "candidate_rounds" and w[1] == "insert_many"]


@_pytest.mark.asyncio
async def test_update_interview_plan_404():
    fake = _FakeSb()
    fake.selects["requisitions"] = [None]
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.update_interview_plan("x", InterviewPlanCreate(rounds=[]))
    assert ei.value.status_code == 404


# --- delete_interview_plan -------------------------------------------------
@_pytest.mark.asyncio
async def test_delete_interview_plan_resets_status():
    fake = _FakeSb()
    fake.selects["requisitions"] = [{"id": "req-1"}]
    fake.selects["rounds"] = [[{"id": "r1"}]]
    svc = RequisitionService(fake)
    out = await svc.delete_interview_plan("req-1")
    assert "deleted" in out["message"].lower()
    req_upd = fake.writes_to("requisitions", "update")
    assert any(w[2].get("status") == "intake_pending" for w in req_upd)


@_pytest.mark.asyncio
async def test_delete_interview_plan_404():
    fake = _FakeSb()
    fake.selects["requisitions"] = [None]
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.delete_interview_plan("x")
    assert ei.value.status_code == 404


# --- add_round -------------------------------------------------------------
@_pytest.mark.asyncio
async def test_add_round_assigns_next_number_and_backfills_candidates(monkeypatch):
    fake = _FakeSb()
    # asyncio.gather: req single, rounds(round_number) list
    fake.selects["requisitions"] = [{"id": "req-1"}]
    fake.selects["rounds"] = [[{"round_number": 1}, {"round_number": 2}]]
    fake.writes_return["rounds"] = {"id": "round-new", "round_number": 3, "duration_minutes": 45}
    fake.selects["candidates"] = [[{"id": "cand-1"}, {"id": "cand-2"}]]
    _stub_insert_many(monkeypatch, fake)
    svc = RequisitionService(fake)
    out = await svc.add_round("req-1", RoundCreate(name="New", duration_minutes=45))
    assert out["feedback_questions"] == []
    ins = fake.writes_to("rounds", "insert")[0][2]
    assert ins["round_number"] == 3
    cr = [w for w in fake.writes if w[0] == "candidate_rounds" and w[1] == "insert_many"]
    assert cr and len(cr[0][2]) == 2


@_pytest.mark.asyncio
async def test_add_round_404_missing_req():
    fake = _FakeSb()
    fake.selects["requisitions"] = [None]
    fake.selects["rounds"] = [[]]
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.add_round("x", RoundCreate(name="N"))
    assert ei.value.status_code == 404


# --- update_round ----------------------------------------------------------
@_pytest.mark.asyncio
async def test_update_round_applies_changes():
    fake = _FakeSb()
    fake.selects["rounds"] = [{"id": "r1"}]
    fake.writes_return["rounds"] = {"id": "r1", "name": "Renamed", "duration_minutes": 60}
    svc = RequisitionService(fake)
    out = await svc.update_round("r1", RoundUpdate(name="Renamed", duration_minutes=60))
    assert out["name"] == "Renamed"


@_pytest.mark.asyncio
async def test_update_round_noop_returns_current():
    fake = _FakeSb()
    fake.selects["rounds"] = [
        {"id": "r1"},  # existence check
        {"id": "r1", "name": "Unchanged", "duration_minutes": 45},  # re-read
    ]
    svc = RequisitionService(fake)
    out = await svc.update_round("r1", RoundUpdate())
    assert out["name"] == "Unchanged"
    assert fake.writes_to("rounds", "update") == []


@_pytest.mark.asyncio
async def test_update_round_404():
    fake = _FakeSb()
    fake.selects["rounds"] = [None]
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.update_round("x", RoundUpdate(name="N"))
    assert ei.value.status_code == 404


# --- delete_round / restore_round -----------------------------------------
@_pytest.mark.asyncio
async def test_delete_round_soft_deletes():
    fake = _FakeSb()
    fake.selects["rounds"] = [{"id": "r1", "deleted_at": None}]
    svc = RequisitionService(fake)
    out = await svc.delete_round("r1")
    assert out["id"] == "r1"
    assert fake.writes_to("rounds", "update")
    assert fake.writes_to("feedback_questions", "update")


@_pytest.mark.asyncio
async def test_delete_round_already_deleted_400():
    fake = _FakeSb()
    fake.selects["rounds"] = [{"id": "r1", "deleted_at": "x"}]
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.delete_round("r1")
    assert ei.value.status_code == 400


@_pytest.mark.asyncio
async def test_restore_round_restores():
    fake = _FakeSb()
    fake.selects["rounds"] = [{"id": "r1", "deleted_at": "x"}]
    svc = RequisitionService(fake)
    out = await svc.restore_round("r1")
    assert out["id"] == "r1"


@_pytest.mark.asyncio
async def test_restore_round_not_deleted_400():
    fake = _FakeSb()
    fake.selects["rounds"] = [{"id": "r1", "deleted_at": None}]
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.restore_round("r1")
    assert ei.value.status_code == 400


# --- add_question / update_question / delete / restore ---------------------
@_pytest.mark.asyncio
async def test_add_question_assigns_next_number():
    fake = _FakeSb()
    # gather: rounds single, feedback_questions(question_number) list
    fake.selects["rounds"] = [{"id": "r1"}]
    fake.selects["feedback_questions"] = [
        [{"question_number": 1}, {"question_number": 3}],
    ]
    fake.writes_return["feedback_questions"] = {"id": "q-new", "question_number": 4}
    svc = RequisitionService(fake)
    out = await svc.add_question("r1", FeedbackQuestionCreate(heading="New"))
    assert out["question_number"] == 4
    ins = fake.writes_to("feedback_questions", "insert")[0][2]
    assert ins["question_number"] == 4


@_pytest.mark.asyncio
async def test_add_question_404_missing_round():
    fake = _FakeSb()
    fake.selects["rounds"] = [None]
    fake.selects["feedback_questions"] = [[]]
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.add_question("x", FeedbackQuestionCreate(heading="N"))
    assert ei.value.status_code == 404


@_pytest.mark.asyncio
async def test_update_question_applies():
    fake = _FakeSb()
    fake.selects["feedback_questions"] = [{"id": "q1"}]
    fake.writes_return["feedback_questions"] = {"id": "q1", "heading": "Edited"}
    svc = RequisitionService(fake)
    out = await svc.update_question("q1", FeedbackQuestionUpdate(heading="Edited"))
    assert out["heading"] == "Edited"


@_pytest.mark.asyncio
async def test_update_question_noop_returns_current():
    fake = _FakeSb()
    fake.selects["feedback_questions"] = [
        {"id": "q1"},
        {"id": "q1", "heading": "Same"},
    ]
    svc = RequisitionService(fake)
    out = await svc.update_question("q1", FeedbackQuestionUpdate())
    assert out["heading"] == "Same"
    assert fake.writes_to("feedback_questions", "update") == []


@_pytest.mark.asyncio
async def test_delete_question_soft_deletes():
    fake = _FakeSb()
    fake.selects["feedback_questions"] = [{"id": "q1", "deleted_at": None}]
    svc = RequisitionService(fake)
    out = await svc.delete_question("q1")
    assert out["id"] == "q1"
    assert fake.writes_to("feedback_questions", "update")


@_pytest.mark.asyncio
async def test_delete_question_already_deleted_400():
    fake = _FakeSb()
    fake.selects["feedback_questions"] = [{"id": "q1", "deleted_at": "x"}]
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.delete_question("q1")
    assert ei.value.status_code == 400


@_pytest.mark.asyncio
async def test_restore_question_restores():
    fake = _FakeSb()
    fake.selects["feedback_questions"] = [{"id": "q1", "deleted_at": "x"}]
    svc = RequisitionService(fake)
    out = await svc.restore_question("q1")
    assert out["id"] == "q1"


@_pytest.mark.asyncio
async def test_restore_question_not_deleted_400():
    fake = _FakeSb()
    fake.selects["feedback_questions"] = [{"id": "q1", "deleted_at": None}]
    svc = RequisitionService(fake)
    with _pytest.raises(HTTPException) as ei:
        await svc.restore_question("q1")
    assert ei.value.status_code == 400


# --- _persist_round_questions edge: empty list -> [] ----------------------
@_pytest.mark.asyncio
async def test_persist_round_questions_empty_returns_empty():
    fake = _FakeSb()
    svc = RequisitionService(fake)
    assert await svc._persist_round_questions("r1", []) == []


# --- response builders -----------------------------------------------------
def test_build_round_response_defaults():
    out = rs.build_round_response({"id": "r1"})
    assert out["duration_display"] == "45 mins"
    assert out["skills"] == []
    assert out["guidelines"] == []
