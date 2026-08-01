"""apply_event: ledger row → parse → adapter → policy RPC → EventOutcome."""

from tests.helpers.mock_data import ORG_ID
from tests.helpers.supabase_mocks import mock_rpc, mock_select

from app.services.ats_sync.handlers import apply_event
from app.services.supabase import get_supabase_admin_client

CONN_ROW = {
    "id": "33333333-3333-4333-8333-333333333333",
    "organization_id": ORG_ID,
    "provider": "workable",
    "status": "active",
}

JOB_EVENT_DATA = {"info": {"id": "j1", "title": "SWE", "status": "OPEN"}}
APP_EVENT_DATA = {
    "info": {
        "id": "a1",
        "status": "ACTIVE",
        "candidate": {
            "id": "c1",
            "firstName": "Emily",
            "lastName": "Watson",
            "emails": [{"type": "PERSONAL", "email": "emily@x.co"}],
        },
        "jobId": "j1",
    },
    "currentStage": {"id": "s1", "text": "Screen"},
}
APP_EVENT_NO_EMAIL = {
    "info": {
        "id": "a2",
        "status": "ACTIVE",
        "candidate": {"id": "c2", "firstName": "Bo", "emails": None},
        "jobId": "j1",
    }
}


def row(event_type, data_type, event_data, *, integration_id="int-1", record_id="r"):
    return {
        "event_id": "evt-x",
        "integration_id": integration_id,
        "retry_count": 0,
        "payload": {
            "eventType": event_type,
            "syncDataType": data_type,
            "eventData": event_data,
            "recordId": record_id,
        },
    }


async def test_job_record_new_applies(respx_mock):
    mock_select(respx_mock, "ats_connections", [CONN_ROW])
    rpc = mock_rpc(
        respx_mock, "ats_import_job", {"action": "created", "requisition_id": "r1"}
    )
    outcome = await apply_event(
        get_supabase_admin_client(), row("record.new", "ats_jobs", JOB_EVENT_DATA)
    )
    assert outcome.status == "applied"
    assert rpc.call_count == 1


async def test_application_record_new_applies(respx_mock):
    mock_select(respx_mock, "ats_connections", [CONN_ROW])
    rpc = mock_rpc(
        respx_mock,
        "ats_upsert_candidate",
        {"action": "created", "candidate_id": "c1"},
    )
    outcome = await apply_event(
        get_supabase_admin_client(),
        row("record.new", "ats_applications", APP_EVENT_DATA),
    )
    assert outcome.status == "applied"
    import json

    sent = json.loads(rpc.calls[0].request.content)
    assert sent["p_fields"]["email"] == "emily@x.co"
    assert sent["p_stage_name"] == "Screen"
    # fast-lane partial profile is always passed (empty here — no location/links)
    assert sent["p_profile"] == {}


async def test_application_orphaned(respx_mock):
    mock_select(respx_mock, "ats_connections", [CONN_ROW])
    mock_rpc(respx_mock, "ats_upsert_candidate", {"action": "orphaned"})
    outcome = await apply_event(
        get_supabase_admin_client(),
        row("record.new", "ats_applications", APP_EVENT_DATA),
    )
    assert outcome.status == "orphaned"


async def test_application_skip_no_email(respx_mock):
    mock_select(respx_mock, "ats_connections", [CONN_ROW])
    outcome = await apply_event(
        get_supabase_admin_client(),
        row("record.new", "ats_applications", APP_EVENT_NO_EMAIL),
    )
    assert outcome.status == "applied_with_skip"
    assert outcome.detail == "no_email"


async def test_record_deleted_routes_to_mark_deleted(respx_mock):
    mock_select(respx_mock, "ats_connections", [CONN_ROW])
    rpc = mock_rpc(respx_mock, "ats_mark_deleted", {"action": "soft_deleted"})
    outcome = await apply_event(
        get_supabase_admin_client(),
        row("record.deleted", "ats_jobs", {}, record_id="j1"),
    )
    assert outcome.status == "applied"
    import json

    sent = json.loads(rpc.calls[0].request.content)
    assert sent["p_ats_type"] == "job" and sent["p_ats_id"] == "j1"


async def test_sync_heartbeat_is_bookkeeping(respx_mock):
    outcome = await apply_event(
        get_supabase_admin_client(), row("sync.heartbeat", "ats_jobs", {})
    )
    assert outcome.status == "bookkeeping"


async def test_unknown_event_type_ignored(respx_mock):
    outcome = await apply_event(
        get_supabase_admin_client(), row("something.else", "ats_jobs", {})
    )
    assert outcome.status == "ignored"


async def test_unknown_integration_fails(respx_mock):
    mock_select(respx_mock, "ats_connections", [])
    outcome = await apply_event(
        get_supabase_admin_client(), row("record.new", "ats_jobs", JOB_EVENT_DATA)
    )
    assert outcome.status == "failed"
    assert "unknown integration" in outcome.detail


async def test_unparseable_job_event_fails(respx_mock):
    mock_select(respx_mock, "ats_connections", [CONN_ROW])
    outcome = await apply_event(
        get_supabase_admin_client(), row("record.new", "ats_jobs", {"stages": []})
    )
    assert outcome.status == "failed"
    assert "unparseable" in outcome.detail


async def test_application_apply_triggers_interview_pull(respx_mock, monkeypatch):
    mock_select(respx_mock, "ats_connections", [CONN_ROW])
    mock_rpc(respx_mock, "ats_upsert_candidate", {"action": "created", "candidate_id": "c1"})

    calls: list[tuple] = []

    async def fake_pull(supabase, bundle, org_id, application_id):
        calls.append((org_id, application_id))
        return 2

    # Patch the registry + pull where handlers.py references them.
    import app.services.ats_sync.handlers as handlers

    async def fake_bundle(_sb, _org):
        class _B:
            connection_id = "conn-1"
            provider = "workable"
            knit_integration_id = "iid-1"
            interviews = object()
        return _B()

    monkeypatch.setattr(handlers, "get_ats_provider", fake_bundle)
    monkeypatch.setattr(handlers, "pull_interviews_for_application", fake_pull)

    outcome = await apply_event(
        get_supabase_admin_client(),
        row("record.new", "ats_applications", APP_EVENT_DATA),
    )
    assert outcome.status == "applied"
    assert calls == [(ORG_ID, "a1")]


async def test_interview_pull_failure_does_not_fail_application(respx_mock, monkeypatch):
    mock_select(respx_mock, "ats_connections", [CONN_ROW])
    mock_rpc(respx_mock, "ats_upsert_candidate", {"action": "created", "candidate_id": "c1"})

    import app.services.ats_sync.handlers as handlers

    async def fake_bundle(_sb, _org):
        class _B:
            connection_id = "conn-1"
            provider = "workable"
            knit_integration_id = "iid-1"
            interviews = object()
        return _B()

    async def boom(*_a, **_k):
        raise RuntimeError("ashby down")

    monkeypatch.setattr(handlers, "get_ats_provider", fake_bundle)
    monkeypatch.setattr(handlers, "pull_interviews_for_application", boom)

    outcome = await apply_event(
        get_supabase_admin_client(),
        row("record.new", "ats_applications", APP_EVENT_DATA),
    )
    # candidate upsert still succeeded; interview pull error is swallowed
    assert outcome.status == "applied"


async def test_orphaned_application_does_not_trigger_pull(respx_mock, monkeypatch):
    mock_select(respx_mock, "ats_connections", [CONN_ROW])
    mock_rpc(respx_mock, "ats_upsert_candidate", {"action": "orphaned"})

    import app.services.ats_sync.handlers as handlers
    called = {"n": 0}

    async def fake_pull(*_a, **_k):
        called["n"] += 1
        return 0

    monkeypatch.setattr(handlers, "pull_interviews_for_application", fake_pull)

    outcome = await apply_event(
        get_supabase_admin_client(),
        row("record.new", "ats_applications", APP_EVENT_DATA),
    )
    assert outcome.status == "orphaned"
    assert called["n"] == 0  # no candidate row yet → nothing to attach interviews to
