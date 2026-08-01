"""Jobs group: wire parsing (golden sample from Knit's schema example),
wire→canonical mapping, pagination, paged-scan get_job, create_job."""

import json

import httpx
import pytest
import respx

from app.integrations.ats.core.errors import AtsResourceNotFoundError
from app.integrations.ats.core.models import AtsJobCreate
from app.integrations.ats.unified_knit.apis.jobs.api import KnitJobsApi
from app.integrations.ats.unified_knit.apis.jobs.mapping import to_ats_job
from app.integrations.ats.unified_knit.apis.jobs.wire_models import KnitJob
from app.integrations.ats.unified_knit.transport import KnitTransport

BASE = "https://knit.test/v1.0"

KNIT_JOB = {
    "info": {
        "id": "job-1",
        "title": "Frontend Engineer",
        "description": "Build UIs",
        "createdAt": "2024-11-16T17:20:38Z",
        "updatedAt": "2024-11-16T17:20:39Z",
        "status": "OPEN",
        "confidential": False,
        "infoUrl": "https://x/info",
        "applyUrl": "https://x/apply",
    },
    "departments": [{"id": "d1", "name": "Eng"}],
    "offices": [
        {
            "id": "o1",
            "name": "HQ",
            "location": "SF",
            "address": {"city": "SF", "country": "US"},
        }
    ],
    "hiringManagers": [{"id": "hm1", "email": "hm@x.co", "employeeId": "e1"}],
    "recruiters": [{"id": "r1", "email": "rec@x.co", "employeeId": "e2"}],
    "stages": [{"id": "s1", "text": "Screen"}, {"id": "s2", "text": "Onsite"}],
    "unknownField": {"future": True},
}


# Real Workable-via-Knit payload shape (live-verified 2026-06-11): empty
# collections arrive as explicit null, not [] or absent.
KNIT_JOB_NULL_COLLECTIONS = {
    "info": {"id": "job-9", "title": "Backend Engineer", "status": "OPEN"},
    "departments": None,
    "offices": None,
    "hiringManagers": None,
    "recruiters": None,
    "stages": None,
}


def make_api() -> tuple[KnitJobsApi, KnitTransport]:
    transport = KnitTransport(api_key="k", base_url=BASE)
    return KnitJobsApi(transport, integration_id="int-1"), transport


def test_wire_parse_tolerates_null_collections():
    job = to_ats_job(KnitJob.model_validate(KNIT_JOB_NULL_COLLECTIONS))
    assert job.id == "job-9"
    assert job.departments == [] and job.offices == []
    assert job.hiring_managers == [] and job.recruiters == [] and job.stages == []


def test_wire_parse_ignores_unknown_and_maps_canonical():
    wire = KnitJob.model_validate(KNIT_JOB)
    job = to_ats_job(wire)
    assert job.id == "job-1" and job.title == "Frontend Engineer"
    assert job.status == "OPEN"
    assert [s.name for s in job.stages] == ["Screen", "Onsite"]
    assert job.offices[0].location == "SF"
    assert job.hiring_managers[0].email == "hm@x.co"
    assert job.departments[0].name == "Eng"
    assert job.created_at == "2024-11-16T17:20:38Z"


async def test_list_jobs_paginates():
    with respx.mock as mock:
        route = mock.get(f"{BASE}/ats.job.list").respond(
            200,
            json={
                "success": True,
                "data": {"jobs": [KNIT_JOB], "nextPageToken": "tok-2"},
            },
        )
        api, transport = make_api()
        page = await api.list_jobs(page_token="tok-1")
        await transport.aclose()
    assert page.next_page_token == "tok-2"
    assert page.items[0].title == "Frontend Engineer"
    assert "pageToken=tok-1" in str(route.calls[0].request.url)


async def test_list_jobs_first_page_sends_no_token():
    with respx.mock as mock:
        route = mock.get(f"{BASE}/ats.job.list").respond(
            200, json={"success": True, "data": {"jobs": []}}
        )
        api, transport = make_api()
        page = await api.list_jobs()
        await transport.aclose()
    assert "pageToken" not in str(route.calls[0].request.url)
    assert page.items == [] and page.next_page_token is None


async def test_get_job_scans_pages_until_found():
    other = {**KNIT_JOB, "info": {**KNIT_JOB["info"], "id": "job-0"}}
    with respx.mock as mock:
        route = mock.get(f"{BASE}/ats.job.list")
        route.side_effect = [
            httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"jobs": [other], "nextPageToken": "t2"},
                },
            ),
            httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"jobs": [KNIT_JOB], "nextPageToken": None},
                },
            ),
        ]
        api, transport = make_api()
        job = await api.get_job("job-1")
        await transport.aclose()
    assert job.id == "job-1"
    assert route.call_count == 2


async def test_get_job_not_found_after_exhausting_pages():
    with respx.mock as mock:
        mock.get(f"{BASE}/ats.job.list").respond(
            200, json={"success": True, "data": {"jobs": [], "nextPageToken": None}}
        )
        api, transport = make_api()
        with pytest.raises(AtsResourceNotFoundError):
            await api.get_job("nope")
        await transport.aclose()


async def test_create_job_posts_payload_and_returns_id():
    with respx.mock as mock:
        route = mock.post(f"{BASE}/ats.job.create").respond(
            200, json={"success": True, "data": {"jobId": "new-1"}}
        )
        api, transport = make_api()
        new_id = await api.create_job(AtsJobCreate(title="SWE", description="d"))
        await transport.aclose()
    assert new_id == "new-1"
    sent = json.loads(route.calls[0].request.content)
    assert sent == {"title": "SWE", "description": "d"}
