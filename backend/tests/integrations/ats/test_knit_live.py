"""Live tests against real Knit + the connected Workable account.

Run manually (host or container with network):
  KNIT_LIVE_TESTS=1 KNIT_LIVE_API_KEY=<real> KNIT_TEST_INTEGRATION_ID=<int-id> \
    python -m pytest tests/integrations/ats/test_knit_live.py -m knit_live -v --no-cov

Excluded from CI/coverage (skipped unless KNIT_LIVE_TESTS is set). Uses
KNIT_LIVE_API_KEY — NOT KNIT_API_KEY — so the conftest test stub never masks
the real key.
"""

import os

import pytest

from app.integrations.ats.core.models import CandidateSearchCriteria
from app.integrations.ats.unified_knit.apis.candidates.api import KnitCandidatesApi
from app.integrations.ats.unified_knit.apis.jobs.api import KnitJobsApi
from app.integrations.ats.unified_knit.transport import KnitTransport

pytestmark = [
    pytest.mark.knit_live,
    pytest.mark.skipif(
        not os.environ.get("KNIT_LIVE_TESTS"),
        reason="KNIT_LIVE_TESTS not set",
    ),
]


@pytest.fixture
async def transport():
    knit_transport = KnitTransport(
        api_key=os.environ["KNIT_LIVE_API_KEY"],
        base_url="https://api.getknit.dev/v1.0",
    )
    yield knit_transport
    await knit_transport.aclose()


@pytest.fixture
def integration_id() -> str:
    return os.environ["KNIT_TEST_INTEGRATION_ID"]


async def test_live_list_jobs(transport, integration_id):
    page = await KnitJobsApi(transport, integration_id).list_jobs()
    assert isinstance(page.items, list)
    for job in page.items:
        assert job.id and job.title


async def test_live_get_job_roundtrip(transport, integration_id):
    api = KnitJobsApi(transport, integration_id)
    page = await api.list_jobs()
    if not page.items:
        pytest.skip("no jobs in the test Workable account")
    job = await api.get_job(page.items[0].id)
    assert job.id == page.items[0].id


async def test_live_list_applications(transport, integration_id):
    page = await KnitCandidatesApi(transport, integration_id).list_applications()
    assert isinstance(page.items, list)
    for application in page.items:
        assert application.id and application.candidate.id


async def test_live_search_candidates(transport, integration_id):
    # Two Workable-connector behaviors, live-verified 2026-06-11:
    #  1. application.list returns SLIM entries (candidate fields null) —
    #     full candidate data only comes from application.get.
    #  2. search requires `emails` (name-only → 400 "'emails' must be a
    #     non-empty JSON array string").
    # So: list → enrich first app via get_application → search by its email.
    api = KnitCandidatesApi(transport, integration_id)
    page = await api.list_applications()
    if not page.items:
        pytest.skip("no applications in the test Workable account")
    first = page.items[0]
    detail = await api.get_application(first.id, first.candidate.id)
    if not detail.candidate.emails:
        pytest.skip("first application's candidate has no email")
    candidate_email = detail.candidate.emails[0].value
    results = await api.search_candidates(
        CandidateSearchCriteria(email=candidate_email)
    )
    assert isinstance(results, list) and len(results) >= 1
    assert any(
        any(e.value == candidate_email for e in c.emails) for c in results
    )
