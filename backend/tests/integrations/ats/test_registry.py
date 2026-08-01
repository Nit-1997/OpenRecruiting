"""Registry: org → active ats_connections row → provider bundle."""

import pytest

from app.integrations.ats.core.errors import AtsNotConnectedError
from app.integrations.ats.core.registry import get_ats_provider
from app.services.supabase import get_supabase_admin_client
from tests.helpers.mock_data import ORG_ID
from tests.helpers.supabase_mocks import mock_select

ROW = {
    "id": "conn-1",
    "provider": "workable",
    "knit_integration_id": "int-1",
}


async def test_returns_bundle_for_active_connection(respx_mock):
    mock_select(respx_mock, "ats_connections", [ROW])
    bundle = await get_ats_provider(get_supabase_admin_client(), ORG_ID)
    assert bundle.provider == "workable"
    assert bundle.connection_id == "conn-1"
    assert bundle.knit_integration_id == "int-1"
    assert bundle.jobs is not None and bundle.candidates is not None


async def test_raises_when_no_active_connection(respx_mock):
    mock_select(respx_mock, "ats_connections", [])
    with pytest.raises(AtsNotConnectedError):
        await get_ats_provider(get_supabase_admin_client(), ORG_ID)


async def test_registry_selects_ashby_native(respx_mock):
    from app.integrations.ats.passthrough.ashby.candidates import AshbyCandidatesAdapter
    from app.integrations.ats.passthrough.ashby.interviews import AshbyInterviewsAdapter
    from app.integrations.ats.passthrough.ashby.scorecards import AshbyScorecardsAdapter

    mock_select(
        respx_mock,
        "ats_connections",
        [{"id": "conn-1", "provider": "ashby", "knit_integration_id": "iid-1"}],
    )
    bundle = await get_ats_provider(get_supabase_admin_client(), ORG_ID)
    assert isinstance(bundle.candidates, AshbyCandidatesAdapter)
    assert isinstance(bundle.scorecards, AshbyScorecardsAdapter)
    assert isinstance(bundle.interviews, AshbyInterviewsAdapter)


async def test_registry_selects_workable_native(respx_mock):
    from app.integrations.ats.passthrough.workable.candidates import WorkableCandidatesAdapter
    from app.integrations.ats.passthrough.workable.scorecards import WorkableScorecardsAdapter

    mock_select(
        respx_mock,
        "ats_connections",
        [{"id": "conn-1", "provider": "workable", "knit_integration_id": "iid-1"}],
    )
    bundle = await get_ats_provider(get_supabase_admin_client(), ORG_ID)
    assert isinstance(bundle.candidates, WorkableCandidatesAdapter)
    assert isinstance(bundle.scorecards, WorkableScorecardsAdapter)


async def test_registry_defaults_to_unified(respx_mock):
    from app.integrations.ats.unified_knit.apis.candidates.api import KnitCandidatesApi

    mock_select(
        respx_mock,
        "ats_connections",
        [{"id": "conn-1", "provider": "lever", "knit_integration_id": "iid-1"}],
    )
    bundle = await get_ats_provider(get_supabase_admin_client(), ORG_ID)
    assert isinstance(bundle.candidates, KnitCandidatesApi)
    assert bundle.scorecards is None
    assert bundle.interviews is None
