"""reconcile_interviews_once: for each active connection, pull interviews for each
linked application id via the shared idempotent path. Convergence (no double-ingest)
is guaranteed by the RPC key — this test asserts the pull is invoked per application
and that a per-application failure never aborts the connection sweep."""

from tests.helpers.mock_data import ORG_ID
from tests.helpers.supabase_mocks import mock_select

from app.services.ats_sync import interview_reconcile
from app.services.supabase import get_supabase_admin_client

CONN = {
    "id": "conn-1",
    "organization_id": ORG_ID,
    "provider": "ashby",
    "knit_integration_id": "iid-1",
}


def _link(ats_id):
    return {"ats_id": ats_id}


async def test_reconcile_pulls_each_application(respx_mock, monkeypatch):
    # First select → active connections; second select → application links.
    # respx routes by table URL, so each table's GET resolves independently.
    mock_select(respx_mock, "ats_connections", [CONN])
    mock_select(respx_mock, "ats_entity_links", [_link("app-1"), _link("app-2")])
    # Phase C post-upsert promotion discovery: nothing un-promoted -> no-op.
    mock_select(respx_mock, "ats_interviews", [])

    async def fake_bundle(_sb, _org):
        class _B:
            connection_id = "conn-1"
            provider = "ashby"
            knit_integration_id = "iid-1"
            interviews = object()
        return _B()

    pulled: list[str] = []

    async def fake_pull(_sb, _bundle, _org, application_id):
        pulled.append(application_id)
        return 1

    monkeypatch.setattr(interview_reconcile, "get_ats_provider", fake_bundle)
    monkeypatch.setattr(interview_reconcile, "pull_interviews_for_application", fake_pull)

    total = await interview_reconcile.reconcile_interviews_once(
        get_supabase_admin_client()
    )
    assert sorted(pulled) == ["app-1", "app-2"]
    assert total == 2  # total events upserted (1 per app)


async def test_reconcile_per_application_failure_is_isolated(respx_mock, monkeypatch):
    mock_select(respx_mock, "ats_connections", [CONN])
    mock_select(respx_mock, "ats_entity_links", [_link("app-1"), _link("app-2")])
    # Phase C post-upsert promotion discovery: nothing un-promoted -> no-op.
    mock_select(respx_mock, "ats_interviews", [])

    async def fake_bundle(_sb, _org):
        class _B:
            connection_id = "conn-1"
            provider = "ashby"
            knit_integration_id = "iid-1"
            interviews = object()
        return _B()

    seen: list[str] = []

    async def fake_pull(_sb, _bundle, _org, application_id):
        seen.append(application_id)
        if application_id == "app-1":
            raise RuntimeError("ashby 500")
        return 1

    monkeypatch.setattr(interview_reconcile, "get_ats_provider", fake_bundle)
    monkeypatch.setattr(interview_reconcile, "pull_interviews_for_application", fake_pull)

    n = await interview_reconcile.reconcile_interviews_once(get_supabase_admin_client())
    assert sorted(seen) == ["app-1", "app-2"]  # app-2 still attempted after app-1 failed
    assert n == 1  # only app-2 succeeded


async def test_reconcile_no_connections_is_noop(respx_mock, monkeypatch):
    mock_select(respx_mock, "ats_connections", [])
    called = {"bundle": 0}

    async def fake_bundle(_sb, _org):
        called["bundle"] += 1

    monkeypatch.setattr(interview_reconcile, "get_ats_provider", fake_bundle)
    n = await interview_reconcile.reconcile_interviews_once(get_supabase_admin_client())
    assert n == 0
    assert called["bundle"] == 0


def test_run_ats_interview_reconcile_is_exposed_for_lifespan():
    # main.py imports this symbol inside the ATS-enabled lifespan branch.
    from app.services.ats_sync.interview_reconcile import run_ats_interview_reconcile

    assert callable(run_ats_interview_reconcile)
