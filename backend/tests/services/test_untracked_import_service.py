"""BE-T6: behavioural coverage of UntrackedImportService.

Exercises the list/packet read paths, the conflict-code branches, candidate
resolution, transcript copy, source-media resolution, and the cleanup path.
The fake supabase is the same table-routed recorder used by the BE-S5
conflict tests, extended with a per-table response queue, count_async, and a
writes log. Lambda / candidate-service boundaries are monkeypatched.
"""

import pytest

import app.services.untracked_import_service as ims
from app.services.untracked_import_service import (
    UntrackedImportService,
    UntrackedImportError,
    EXISTING_ROUND_CONFLICT_CODE,
    _is_synthetic_email,
    _first_row,
    _now_iso,
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

    def in_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    async def execute_async(self):
        key = (self._table, self._op)
        if self._op in ("insert", "update", "upsert"):
            self._fake.writes.append((self._table, self._op, self._payload))
            if key in self._fake.raise_on:
                raise self._fake.raise_on[key]
            row = dict(self._payload) if isinstance(self._payload, dict) else self._payload
            if isinstance(row, dict):
                row.setdefault("id", self._fake.insert_ids.get(self._table, f"{self._table}-id"))
            return _Resp([row] if isinstance(row, dict) else row)
        queue = self._fake.selects.get(self._table, [])
        data = queue.pop(0) if queue else []
        return _Resp(data)

    async def count_async(self):
        return self._fake.counts.get(self._table, 0)


class _FakeSb:
    def __init__(self):
        self.selects: dict[str, list] = {}
        self.counts: dict[str, int] = {}
        self.insert_ids: dict[str, str] = {}
        self.raise_on: dict[tuple, Exception] = {}
        self.writes: list[tuple] = []

    def table(self, name):
        return _Q(self, name)

    def writes_to(self, table, op):
        return [w for w in self.writes if w[0] == table and w[1] == op]


def _patch_candidate_service(monkeypatch, candidate_id="new-cand"):
    class _CandSvc:
        async def add_candidate(self, **_k):
            return {"candidate": {"id": candidate_id}}

    monkeypatch.setattr(ims, "get_candidate_service", lambda: _CandSvc())


def _patch_feedback(monkeypatch, status="accepted", reason=None, boom=False):
    calls = []

    class _Job:
        async def trigger_feedback_processing(self, cr_id, skip_prereq_check=False):
            calls.append(cr_id)
            if boom:
                raise RuntimeError("lambda down")
            out = {"status": status}
            if reason:
                out["reason"] = reason
            return out

    monkeypatch.setattr(ims, "get_feedback_job_service", lambda: _Job())
    return calls


# --- small helpers ---------------------------------------------------------
def test_is_synthetic_email():
    assert _is_synthetic_email("x@untracked.local") is True
    assert _is_synthetic_email("real@test.com") is False


def test_first_row_variants():
    assert _first_row([{"a": 1}, {"a": 2}]) == {"a": 1}
    assert _first_row([]) is None
    assert _first_row({"a": 1}) == {"a": 1}
    assert _first_row(None) is None


def test_module_is_unique_violation_delegates():
    assert ims._is_unique_violation(PostgrestError("dup", code="23505")) is True
    assert ims._is_unique_violation(RuntimeError("nope")) is False


# --- list_target_rounds ----------------------------------------------------
@pytest.mark.asyncio
async def test_list_target_rounds_returns_rounds():
    fake = _FakeSb()
    fake.selects["requisitions"] = [[{"id": "req-1", "organization_id": ORG_ID, "is_system_template": False}]]
    fake.selects["rounds"] = [[{"id": "r1", "name": "Tech", "round_number": 1}]]
    svc = UntrackedImportService(fake)
    out = await svc.list_target_rounds("req-1", ORG_ID)
    assert out[0]["name"] == "Tech"


@pytest.mark.asyncio
async def test_list_target_rounds_rejects_system_template():
    fake = _FakeSb()
    fake.selects["requisitions"] = [[{"id": "req-1", "organization_id": ORG_ID, "is_system_template": True}]]
    svc = UntrackedImportService(fake)
    with pytest.raises(UntrackedImportError) as ei:
        await svc.list_target_rounds("req-1", ORG_ID)
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_get_requisition_404_and_forbidden():
    fake = _FakeSb()
    fake.selects["requisitions"] = [[]]
    svc = UntrackedImportService(fake)
    with pytest.raises(UntrackedImportError) as ei:
        await svc._get_requisition("nope")
    assert ei.value.status_code == 404

    fake2 = _FakeSb()
    fake2.selects["requisitions"] = [[{"id": "req-1", "organization_id": "other-org", "is_system_template": False}]]
    svc2 = UntrackedImportService(fake2)
    with pytest.raises(UntrackedImportError) as ei2:
        await svc2._get_target_requisition("req-1", ORG_ID)
    assert ei2.value.status_code == 403


# --- _list_generic_capture_rows + list_untracked_interviews ----------------
def _binding_row():
    return [{"materialized_requisition_id": "generic-req"}]


@pytest.mark.asyncio
async def test_list_generic_capture_rows_no_binding_returns_empty():
    fake = _FakeSb()
    fake.selects["org_generic_template_bindings"] = [[]]
    svc = UntrackedImportService(fake)
    rows = await svc._list_generic_capture_rows(ORG_ID, date_from=None, date_to=None)
    assert rows == []


@pytest.mark.asyncio
async def test_list_generic_capture_rows_builds_and_sorts():
    fake = _FakeSb()
    fake.selects["org_generic_template_bindings"] = [_binding_row()]
    fake.selects["candidates"] = [[
        {"id": "c1", "requisition_id": "generic-req", "name": "Alice", "email": "a@x.com"},
    ]]
    fake.selects["candidate_rounds"] = [[
        {"id": "cr-old", "candidate_id": "c1", "origin_detection_id": "det-old",
         "interviewer_email": "iv@x.com", "status": "scheduled", "scheduled_at": "2025-01-01T10:00:00Z"},
        {"id": "cr-new", "candidate_id": "c1", "origin_detection_id": "det-new",
         "interviewer_email": "iv@x.com", "status": "scheduled", "scheduled_at": "2025-03-01T10:00:00Z"},
    ]]
    fake.selects["calendar_event_detections"] = [[
        {"id": "det-old", "event_title": "Old", "event_start": "2025-01-01T10:00:00Z"},
        {"id": "det-new", "event_title": "New", "event_start": "2025-03-01T10:00:00Z"},
    ]]
    svc = UntrackedImportService(fake)
    rows = await svc._list_generic_capture_rows(ORG_ID, date_from=None, date_to=None)
    assert len(rows) == 2
    # sorted newest-first by event_start
    assert rows[0]["source_candidate_round_id"] == "cr-new"
    assert rows[0]["candidate_name"] == "Alice"


@pytest.mark.asyncio
async def test_list_untracked_interviews_marks_imported_status():
    fake = _FakeSb()
    # _get_target_requisition
    fake.selects["requisitions"] = [
        [{"id": "tgt-req", "organization_id": ORG_ID, "is_system_template": False}],
        # imported req titles lookup
        [{"id": "tgt-req", "role_title": "Backend"}],
    ]
    fake.selects["org_generic_template_bindings"] = [_binding_row()]
    fake.selects["candidates"] = [[
        {"id": "c1", "requisition_id": "generic-req", "name": "Alice", "email": "a@x.com"},
    ]]
    fake.selects["candidate_rounds"] = [[
        {"id": "cr-1", "candidate_id": "c1", "origin_detection_id": "det-1",
         "interviewer_email": "iv@x.com", "status": "scheduled", "scheduled_at": "2025-03-01T10:00:00Z"},
    ]]
    fake.selects["calendar_event_detections"] = [[
        {"id": "det-1", "event_title": "Interview", "event_start": "2025-03-01T10:00:00Z"},
    ]]
    # imports lookup by source round (returns one prior import)
    fake.selects["untracked_interview_imports"] = [
        [{"id": "imp-1", "source_generic_candidate_round_id": "cr-1",
          "source_detection_id": "det-1", "target_requisition_id": "tgt-req",
          "import_status": "reprocessed", "created_at": "2025-03-02T00:00:00Z"}],
        # by detection lookup (also runs)
        [],
    ]
    svc = UntrackedImportService(fake)
    out = await svc.list_untracked_interviews("tgt-req", ORG_ID, import_view="imported")
    assert out["total"] == 1
    item = out["items"][0]
    assert item["status"] == "reprocessed"
    assert item["imported_requisition_title"] == "Backend"


@pytest.mark.asyncio
async def test_list_untracked_interviews_available_view_filters_imported():
    fake = _FakeSb()
    fake.selects["requisitions"] = [
        [{"id": "tgt-req", "organization_id": ORG_ID, "is_system_template": False}],
    ]
    fake.selects["org_generic_template_bindings"] = [_binding_row()]
    fake.selects["candidates"] = [[
        {"id": "c1", "requisition_id": "generic-req", "name": "Alice", "email": "a@x.com"},
    ]]
    fake.selects["candidate_rounds"] = [[
        {"id": "cr-1", "candidate_id": "c1", "origin_detection_id": "det-1",
         "interviewer_email": "iv@x.com", "status": "scheduled", "scheduled_at": "2025-03-01T10:00:00Z"},
    ]]
    fake.selects["calendar_event_detections"] = [[
        {"id": "det-1", "event_title": "Interview", "event_start": "2025-03-01T10:00:00Z"},
    ]]
    fake.selects["untracked_interview_imports"] = [
        [{"id": "imp-1", "source_generic_candidate_round_id": "cr-1",
          "source_detection_id": "det-1", "target_requisition_id": "tgt-req",
          "import_status": "reprocessed", "created_at": "2025-03-02T00:00:00Z"}],
        [],
    ]
    svc = UntrackedImportService(fake)
    out = await svc.list_untracked_interviews("tgt-req", ORG_ID, import_view="available")
    # the one record is imported -> filtered out of available view
    assert out["total"] == 0


@pytest.mark.asyncio
async def test_list_untracked_interviews_empty_when_no_records():
    fake = _FakeSb()
    fake.selects["requisitions"] = [
        [{"id": "tgt-req", "organization_id": ORG_ID, "is_system_template": False}],
    ]
    fake.selects["org_generic_template_bindings"] = [[]]  # no binding -> no records
    svc = UntrackedImportService(fake)
    out = await svc.list_untracked_interviews("tgt-req", ORG_ID)
    assert out == {"items": [], "total": 0, "page": 1, "page_size": 25}


@pytest.mark.asyncio
async def test_list_org_untracked_interviews_marks_status():
    fake = _FakeSb()
    fake.selects["org_generic_template_bindings"] = [_binding_row()]
    fake.selects["candidates"] = [[
        {"id": "c1", "requisition_id": "generic-req", "name": "Alice", "email": "a@x.com"},
    ]]
    fake.selects["candidate_rounds"] = [[
        {"id": "cr-1", "candidate_id": "c1", "origin_detection_id": "det-1",
         "interviewer_email": "iv@x.com", "status": "scheduled", "scheduled_at": "2025-03-01T10:00:00Z"},
    ]]
    fake.selects["calendar_event_detections"] = [[
        {"id": "det-1", "event_title": "Interview", "event_start": "2025-03-01T10:00:00Z"},
    ]]
    fake.selects["untracked_interview_imports"] = [
        # by source
        [{"source_generic_candidate_round_id": "cr-1", "source_detection_id": "det-1",
          "import_status": "copied", "target_requisition_id": "tgt-req", "created_at": "2025-03-02T00:00:00Z"}],
        # by detection
        [],
    ]
    fake.selects["requisitions"] = [[{"id": "tgt-req", "role_title": "Backend"}]]
    svc = UntrackedImportService(fake)
    out = await svc.list_org_untracked_interviews(ORG_ID, import_view="all")
    assert out["total"] == 1
    assert out["items"][0]["status"] == "copied"
    assert out["items"][0]["imported_requisition_title"] == "Backend"


# --- _filter_rows_by_import_view ------------------------------------------
def test_filter_rows_by_import_view():
    svc = UntrackedImportService(_FakeSb())
    rows = [{"status": "available"}, {"status": "copied"}]
    assert len(svc._filter_rows_by_import_view(rows, "all")) == 2
    assert svc._filter_rows_by_import_view(rows, "imported") == [{"status": "copied"}]
    assert svc._filter_rows_by_import_view(rows, "available") == [{"status": "available"}]


def test_parse_event_start():
    svc = UntrackedImportService(_FakeSb())
    assert svc._parse_event_start("2025-01-01T10:00:00Z") is not None
    assert svc._parse_event_start(None) is None
    assert svc._parse_event_start("garbage") is None


# --- get_untracked_interview_packet ---------------------------------------
@pytest.mark.asyncio
async def test_get_packet_builds_feedback_questions():
    fake = _FakeSb()
    # source candidate_round read (packet variant)
    fake.selects["candidate_rounds"] = [[{
        "id": "src-cr", "candidate_id": "src-cand", "round_id": "src-round",
        "source_type": "untracked_generic", "origin_detection_id": "det-1",
        "status": "completed", "scheduled_at": None, "completed_at": None,
        "interviewer_email": "iv@x.com", "meeting_url": "https://m",
        "transcript_url": "https://t", "recording_url": "https://r",
        "scorecard_transcript": None, "summary": "Good", "rating": "hire",
        "question_summaries": {"1": "Summary for Q1"}, "processing_status": "completed",
    }]]
    fake.selects["candidates"] = [[{
        "id": "src-cand", "requisition_id": "src-req", "name": "Jane", "email": "jane@x.com",
    }]]
    fake.selects["requisitions"] = [[{
        "id": "src-req", "organization_id": ORG_ID, "is_system_template": True, "role_title": "Untracked",
    }]]
    fake.selects["rounds"] = [[{"id": "src-round", "name": "Generic Interview", "round_number": 1}]]
    fake.selects["feedback_questions"] = [[
        {"id": "q1", "question_number": 1, "heading": "Tech", "description": "desc"},
    ]]
    fake.selects["candidate_feedback"] = [[
        {"id": "fb1", "feedback_question_id": "q1", "feedback_text": "Strong",
         "evidence": ["e1"], "evidence_status": "ok", "source": "manual",
         "created_at": "2025-01-01", "updated_at": "2025-01-02"},
    ]]
    fake.selects["calendar_event_detections"] = [[{"event_title": "Interview", "event_start": "2025-03-01T10:00:00Z"}]]
    svc = UntrackedImportService(fake)
    out = await svc.get_untracked_interview_packet("src-cr", ORG_ID)
    assert out["candidate_name"] == "Jane"
    assert out["rating"] == "hire"
    fq = out["feedback_questions"][0]
    assert fq["summary"] == "Summary for Q1"
    assert fq["feedback"][0]["feedback_data"] == "Strong"


@pytest.mark.asyncio
async def test_get_packet_404_when_source_missing():
    fake = _FakeSb()
    fake.selects["candidate_rounds"] = [[]]
    svc = UntrackedImportService(fake)
    with pytest.raises(UntrackedImportError) as ei:
        await svc.get_untracked_interview_packet("nope", ORG_ID)
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_get_packet_400_when_not_generic():
    fake = _FakeSb()
    fake.selects["candidate_rounds"] = [[{
        "id": "src-cr", "candidate_id": "c", "round_id": "r",
        "source_type": "tracked", "origin_detection_id": None,
    }]]
    svc = UntrackedImportService(fake)
    with pytest.raises(UntrackedImportError) as ei:
        await svc.get_untracked_interview_packet("src-cr", ORG_ID)
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_get_packet_403_wrong_org():
    fake = _FakeSb()
    fake.selects["candidate_rounds"] = [[{
        "id": "src-cr", "candidate_id": "src-cand", "round_id": "r",
        "source_type": "untracked_generic", "origin_detection_id": None,
    }]]
    fake.selects["candidates"] = [[{"id": "src-cand", "requisition_id": "src-req", "name": "J", "email": "j@x.com"}]]
    fake.selects["requisitions"] = [[{"id": "src-req", "organization_id": "other", "is_system_template": True, "role_title": "U"}]]
    svc = UntrackedImportService(fake)
    with pytest.raises(UntrackedImportError) as ei:
        await svc.get_untracked_interview_packet("src-cr", ORG_ID)
    assert ei.value.status_code == 403


# --- import_untracked_interview conflict branches --------------------------
def _import_selects(*, existing_import=None, existing_by_detection=None,
                    target_conflict=None, target_email_lookup=None):
    return {
        "candidate_rounds": [
            # _get_source_round
            [{
                "id": "src-cr", "candidate_id": "src-cand", "round_id": "src-round",
                "source_type": "untracked_generic", "origin_detection_id": "det-1",
                "scheduled_at": None, "completed_at": None, "interviewer_email": "iv@x.com",
                "meeting_url": "https://m", "scorecard_transcript": None,
                "transcript_url": "https://t", "recording_url": "https://r",
                "processing_status": None, "scorecard_status": None,
                "summary": None, "rating": None, "question_summaries": None,
                "outcome": None, "outcome_notes": None,
            }],
            # conflict check on (candidate, round)
            target_conflict if target_conflict is not None else [],
        ],
        "candidates": [
            # _get_candidate (source)
            [{"id": "src-cand", "requisition_id": "src-req", "name": "Jane", "email": "jane@x.com"}],
            # _resolve_target_candidate: by source email
            target_email_lookup if target_email_lookup is not None else [],
            # _resolve_target_candidate: by target email
            [],
        ],
        "requisitions": [
            [{"id": "src-req", "organization_id": ORG_ID, "is_system_template": True, "role_title": "U"}],
            [{"id": "tgt-req", "organization_id": ORG_ID, "is_system_template": False, "role_title": "Backend"}],
        ],
        "rounds": [
            [{"id": "tgt-round"}],
        ],
        "untracked_interview_imports": [
            existing_import if existing_import is not None else [],
            existing_by_detection if existing_by_detection is not None else [],
        ],
        # existing transcript row -> _copy_transcript_record takes the copy
        # path (no network fallback download).
        "transcripts": [[{
            "recall_transcript_id": "rt", "provider": "recallai", "full_text": "hi",
            "segments": [{"t": 1}], "raw_transcript_url": "u", "word_count": 5,
            "duration_seconds": 100, "language": "en", "processed_at": "x",
            "feedback_transcript": "fb", "participant_metadata": {},
        }]],
    }


@pytest.mark.asyncio
async def test_import_same_exact_target_collides_on_uq_409(monkeypatch):
    """UNTRACKED-MA: re-importing the EXACT same (source, req, round) supersedes
    the prior active attempt, then the audit insert collides on
    uq_import_source_target (real DB) -> mapped to 409, with the orphan round
    cancelled and no feedback fired. The genuine same-target dedup is preserved.
    """
    _patch_candidate_service(monkeypatch)
    calls = _patch_feedback(monkeypatch)
    fake = _FakeSb()
    fake.selects = _import_selects(
        existing_import=[{
            "id": "imp-0", "target_requisition_id": "tgt-req",
            "target_round_id": "tgt-round", "target_candidate_round_id": "old-cr",
            "import_status": "reprocessed", "superseded_at": None,
        }],
    )
    fake.counts = {"feedback_questions": 1}
    fake.insert_ids = {"candidate_rounds": "new-cr", "untracked_interview_imports": "imp-1"}
    fake.raise_on[("untracked_interview_imports", "insert")] = PostgrestError(
        "duplicate", code="23505")
    svc = UntrackedImportService(fake)
    with pytest.raises(UntrackedImportError) as ei:
        await svc.import_untracked_interview(
            req_id="tgt-req", source_candidate_round_id="src-cr",
            target_round_id="tgt-round", org_id=ORG_ID, imported_by_user_id="u")
    assert ei.value.status_code == 409
    assert "this round" in str(ei.value.detail).lower()
    # Feedback NOT triggered on the losing path.
    assert calls == []
    # The orphan round this request created is cancelled.
    cr_updates = fake.writes_to("candidate_rounds", "update")
    assert any(str(w[2].get("status")) == "cancelled" for w in cr_updates)


@pytest.mark.asyncio
async def test_import_reassign_other_req_supersedes_prior(monkeypatch):
    """UNTRACKED-MA: importing into a DIFFERENT requisition is now a reassign,
    not a 409. The prior active attempt is superseded (superseded_at stamped),
    its round cancelled (feedback KEPT), and the new attempt proceeds + triggers
    feedback once.
    """
    _patch_candidate_service(monkeypatch)
    calls = _patch_feedback(monkeypatch)
    fake = _FakeSb()
    fake.selects = _import_selects(
        existing_import=[{
            "id": "imp-0", "target_requisition_id": "other-req",
            "target_round_id": "x", "target_candidate_round_id": "old-cr",
            "import_status": "reprocessed", "superseded_at": None,
        }],
    )
    fake.counts = {"feedback_questions": 1}
    fake.insert_ids = {"candidate_rounds": "new-cr", "untracked_interview_imports": "imp-1"}
    svc = UntrackedImportService(fake)
    result = await svc.import_untracked_interview(
        req_id="tgt-req", source_candidate_round_id="src-cr",
        target_round_id="tgt-round", org_id=ORG_ID, imported_by_user_id="u")

    assert result["target_candidate_round_id"] == "new-cr"
    assert result["import_status"] == "reprocessed"
    # Feedback triggered exactly once, for the new round.
    assert calls == ["new-cr"]
    # The prior active import was superseded (superseded_at stamped).
    imp_updates = fake.writes_to("untracked_interview_imports", "update")
    assert any(w[2].get("superseded_at") for w in imp_updates), (
        f"prior active import must be superseded; updates={imp_updates}")
    # The prior round was cancelled (no feedback deletion anywhere).
    cr_cancels = [w for w in fake.writes_to("candidate_rounds", "update")
                  if str(w[2].get("status")) == "cancelled"]
    assert cr_cancels, "prior active round must be cancelled"
    assert not fake.writes_to("candidate_feedback", "delete")


@pytest.mark.asyncio
async def test_import_existing_round_conflict_returns_structured_409(monkeypatch):
    _patch_candidate_service(monkeypatch)
    _patch_feedback(monkeypatch)
    fake = _FakeSb()
    fake.selects = _import_selects(
        # existing target candidate matched by source email (candidate NOT created)
        target_email_lookup=[{"id": "existing-cand"}],
        target_conflict=[{
            "id": "conflict-cr", "status": "completed", "source_type": "untracked_copy",
            "origin_candidate_round_id": "prev", "recording_url": "https://r",
            "transcript_url": "https://t", "scorecard_transcript": None, "completed_at": "2025-01-01",
        }],
    )
    svc = UntrackedImportService(fake)
    with pytest.raises(UntrackedImportError) as ei:
        await svc.import_untracked_interview(
            req_id="tgt-req", source_candidate_round_id="src-cr",
            target_round_id="tgt-round", org_id=ORG_ID, imported_by_user_id="u",
            override_existing_round=False)
    assert ei.value.status_code == 409
    assert isinstance(ei.value.detail, dict)
    assert ei.value.detail["code"] == EXISTING_ROUND_CONFLICT_CODE
    assert ei.value.detail["conflict"]["has_recording"] is True
    assert ei.value.detail["conflict"]["has_transcript"] is True


@pytest.mark.asyncio
async def test_import_override_reuses_existing_round(monkeypatch):
    _patch_candidate_service(monkeypatch)
    calls = _patch_feedback(monkeypatch, status="accepted")
    fake = _FakeSb()
    fake.selects = _import_selects(
        target_email_lookup=[{"id": "existing-cand"}],
        target_conflict=[{
            "id": "conflict-cr", "status": "completed", "source_type": "untracked_copy",
            "origin_candidate_round_id": "prev", "recording_url": None,
            "transcript_url": None, "scorecard_transcript": None, "completed_at": None,
        }],
    )
    fake.counts["feedback_questions"] = 2
    svc = UntrackedImportService(fake)
    out = await svc.import_untracked_interview(
        req_id="tgt-req", source_candidate_round_id="src-cr",
        target_round_id="tgt-round", org_id=ORG_ID, imported_by_user_id="u",
        override_existing_round=True)
    # reused the conflict round id (update, not insert)
    assert out["target_candidate_round_id"] == "conflict-cr"
    assert out["import_status"] == "reprocessed"
    assert calls == ["conflict-cr"]
    # candidate_rounds updated (reuse path), not inserted fresh
    assert fake.writes_to("candidate_rounds", "update")


@pytest.mark.asyncio
async def test_import_no_questions_marks_pending_scorecard(monkeypatch):
    _patch_candidate_service(monkeypatch)
    calls = _patch_feedback(monkeypatch)
    fake = _FakeSb()
    fake.selects = _import_selects()
    fake.counts["feedback_questions"] = 0  # no questions -> no trigger
    svc = UntrackedImportService(fake)
    out = await svc.import_untracked_interview(
        req_id="tgt-req", source_candidate_round_id="src-cr",
        target_round_id="tgt-round", org_id=ORG_ID, imported_by_user_id="u")
    assert out["import_status"] == "copied_pending_scorecard"
    assert calls == []  # feedback not triggered


@pytest.mark.asyncio
async def test_import_trigger_not_accepted_marks_reprocess_failed(monkeypatch):
    _patch_candidate_service(monkeypatch)
    _patch_feedback(monkeypatch, status="rejected", reason="too soon")
    fake = _FakeSb()
    fake.selects = _import_selects()
    fake.counts["feedback_questions"] = 1
    svc = UntrackedImportService(fake)
    out = await svc.import_untracked_interview(
        req_id="tgt-req", source_candidate_round_id="src-cr",
        target_round_id="tgt-round", org_id=ORG_ID, imported_by_user_id="u")
    assert out["import_status"] == "reprocess_failed"


@pytest.mark.asyncio
async def test_import_trigger_exception_marks_reprocess_failed(monkeypatch):
    _patch_candidate_service(monkeypatch)
    _patch_feedback(monkeypatch, boom=True)
    fake = _FakeSb()
    fake.selects = _import_selects()
    fake.counts["feedback_questions"] = 1
    svc = UntrackedImportService(fake)
    out = await svc.import_untracked_interview(
        req_id="tgt-req", source_candidate_round_id="src-cr",
        target_round_id="tgt-round", org_id=ORG_ID, imported_by_user_id="u")
    assert out["import_status"] == "reprocess_failed"


@pytest.mark.asyncio
async def test_import_round_not_in_requisition_400(monkeypatch):
    _patch_candidate_service(monkeypatch)
    _patch_feedback(monkeypatch)
    fake = _FakeSb()
    selects = _import_selects()
    selects["rounds"] = [[]]  # target round lookup empty
    fake.selects = selects
    svc = UntrackedImportService(fake)
    with pytest.raises(UntrackedImportError) as ei:
        await svc.import_untracked_interview(
            req_id="tgt-req", source_candidate_round_id="src-cr",
            target_round_id="tgt-round", org_id=ORG_ID, imported_by_user_id="u")
    assert ei.value.status_code == 400


# --- _resolve_target_candidate --------------------------------------------
@pytest.mark.asyncio
async def test_resolve_target_candidate_reuses_by_source_email():
    fake = _FakeSb()
    fake.selects["candidates"] = [[{"id": "existing"}]]
    svc = UntrackedImportService(fake)
    cid, created = await svc._resolve_target_candidate(
        target_requisition_id="tgt-req",
        source_candidate={"email": "real@x.com", "name": "Real"},
        source_candidate_round_id="src-cr", org_id=ORG_ID)
    assert cid == "existing" and created is False


@pytest.mark.asyncio
async def test_resolve_target_candidate_creates_new(monkeypatch):
    _patch_candidate_service(monkeypatch, candidate_id="brand-new")
    fake = _FakeSb()
    # source email lookup -> none; target email lookup -> none
    fake.selects["candidates"] = [[], []]
    svc = UntrackedImportService(fake)
    cid, created = await svc._resolve_target_candidate(
        target_requisition_id="tgt-req",
        source_candidate={"email": "real@x.com", "name": "Real"},
        source_candidate_round_id="src-cr", org_id=ORG_ID)
    assert cid == "brand-new" and created is True


@pytest.mark.asyncio
async def test_resolve_target_candidate_synthetic_email_uses_unknown(monkeypatch):
    _patch_candidate_service(monkeypatch, candidate_id="synthetic-cand")
    fake = _FakeSb()
    # synthetic source email skips the by-source lookup; only target-email lookup runs
    fake.selects["candidates"] = [[]]
    svc = UntrackedImportService(fake)
    cid, created = await svc._resolve_target_candidate(
        target_requisition_id="tgt-req",
        source_candidate={"email": "x@untracked.local", "name": "Unknown"},
        source_candidate_round_id="src-cr", org_id=ORG_ID)
    assert created is True


@pytest.mark.asyncio
async def test_resolve_target_candidate_add_already_exists_rechecks(monkeypatch):
    class _CandSvc:
        async def add_candidate(self, **_k):
            raise ValueError("candidate already exists")

    monkeypatch.setattr(ims, "get_candidate_service", lambda: _CandSvc())
    fake = _FakeSb()
    # source lookup none, target lookup none, then recheck finds it
    fake.selects["candidates"] = [[], [], [{"id": "raced-cand"}]]
    svc = UntrackedImportService(fake)
    cid, created = await svc._resolve_target_candidate(
        target_requisition_id="tgt-req",
        source_candidate={"email": "real@x.com", "name": "Real"},
        source_candidate_round_id="src-cr", org_id=ORG_ID)
    assert cid == "raced-cand" and created is False


# --- _resolve_source_round_media ------------------------------------------
@pytest.mark.asyncio
async def test_resolve_source_media_short_circuits_when_present():
    fake = _FakeSb()
    svc = UntrackedImportService(fake)
    out = await svc._resolve_source_round_media(
        source_candidate_round_id="cr", source_detection_id="det",
        source_round={"recording_url": "https://r", "transcript_url": "https://t"})
    assert out["recording_url"] == "https://r"
    assert fake.writes == []  # no recall_bots lookup needed


@pytest.mark.asyncio
async def test_resolve_source_media_falls_back_to_recall_bot():
    fake = _FakeSb()
    fake.selects["recall_bots"] = [[{
        "recording_url": "https://bot-r", "transcript_url": "https://bot-t",
        "recording_duration_seconds": 1200, "participants": ["a"], "created_at": "x",
    }]]
    svc = UntrackedImportService(fake)
    out = await svc._resolve_source_round_media(
        source_candidate_round_id="cr", source_detection_id="det",
        source_round={"recording_url": None, "transcript_url": None})
    assert out["recording_url"] == "https://bot-r"
    assert out["recording_duration_seconds"] == 1200


@pytest.mark.asyncio
async def test_resolve_source_media_no_bot_returns_originals():
    fake = _FakeSb()
    fake.selects["recall_bots"] = [[], []]
    svc = UntrackedImportService(fake)
    out = await svc._resolve_source_round_media(
        source_candidate_round_id="cr", source_detection_id="det",
        source_round={"recording_url": None, "transcript_url": None})
    assert out["recording_url"] is None


# --- _copy_transcript_record ----------------------------------------------
@pytest.mark.asyncio
async def test_copy_transcript_record_copies_existing():
    fake = _FakeSb()
    fake.selects["transcripts"] = [[{
        "recall_transcript_id": "rt", "provider": "recallai", "full_text": "hi",
        "segments": [{"t": 1}], "raw_transcript_url": "u", "word_count": 5,
        "duration_seconds": 100, "language": "en", "processed_at": "x",
        "feedback_transcript": "fb", "participant_metadata": {},
    }]]
    svc = UntrackedImportService(fake)
    await svc._copy_transcript_record("src-cr", "tgt-cr")
    upserts = fake.writes_to("transcripts", "upsert")
    assert upserts and upserts[0][2]["candidate_round_id"] == "tgt-cr"


@pytest.mark.asyncio
async def test_copy_transcript_record_no_source_no_fallback_is_noop():
    fake = _FakeSb()
    fake.selects["transcripts"] = [[]]
    svc = UntrackedImportService(fake)
    await svc._copy_transcript_record("src-cr", "tgt-cr")
    assert fake.writes_to("transcripts", "upsert") == []


@pytest.mark.asyncio
async def test_copy_transcript_record_fallback_download(monkeypatch):
    fake = _FakeSb()
    fake.selects["transcripts"] = [[]]

    async def _fake_download(self, url):
        return [{"speaker": "A", "text": "hi"}]

    monkeypatch.setattr(UntrackedImportService, "_download_transcript_segments", _fake_download)
    svc = UntrackedImportService(fake)
    await svc._copy_transcript_record(
        "src-cr", "tgt-cr", fallback_transcript_url="https://t",
        fallback_duration_seconds=60, fallback_participants=["a"])
    upserts = fake.writes_to("transcripts", "upsert")
    assert upserts and upserts[0][2]["raw_transcript_url"] == "https://t"


@pytest.mark.asyncio
async def test_copy_transcript_record_fallback_empty_segments_noop(monkeypatch):
    fake = _FakeSb()
    fake.selects["transcripts"] = [[]]

    async def _fake_download(self, url):
        return None

    monkeypatch.setattr(UntrackedImportService, "_download_transcript_segments", _fake_download)
    svc = UntrackedImportService(fake)
    await svc._copy_transcript_record("src-cr", "tgt-cr", fallback_transcript_url="https://t")
    assert fake.writes_to("transcripts", "upsert") == []


# --- _cleanup_orphan_import ------------------------------------------------
@pytest.mark.asyncio
async def test_cleanup_orphan_import_cancels_and_soft_deletes():
    fake = _FakeSb()
    svc = UntrackedImportService(fake)
    await svc._cleanup_orphan_import("orphan-cr", "orphan-cand")
    cr = fake.writes_to("candidate_rounds", "update")
    cand = fake.writes_to("candidates", "update")
    assert any(w[2].get("status") == "cancelled" for w in cr)
    assert any(w[2].get("deleted_at") for w in cand)


@pytest.mark.asyncio
async def test_cleanup_orphan_import_swallows_errors():
    fake = _FakeSb()
    fake.raise_on[("candidate_rounds", "update")] = RuntimeError("db down")
    fake.raise_on[("candidates", "update")] = RuntimeError("db down")
    svc = UntrackedImportService(fake)
    # must not raise
    await svc._cleanup_orphan_import("orphan-cr", "orphan-cand")


@pytest.mark.asyncio
async def test_cleanup_orphan_import_noop_when_nothing():
    fake = _FakeSb()
    svc = UntrackedImportService(fake)
    await svc._cleanup_orphan_import(None, None)
    assert fake.writes == []
