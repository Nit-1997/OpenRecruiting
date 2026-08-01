"""Candidates group: structured search body, application list/get mapping
(incl. Knit's null-heavy real-world payloads — see get-application example
where links/owner/interviews are null)."""

import json

import respx

from app.integrations.ats.core.models import CandidateSearchCriteria
from app.integrations.ats.unified_knit.apis.candidates.api import KnitCandidatesApi
from app.integrations.ats.unified_knit.transport import KnitTransport

BASE = "https://knit.test/v1.0"

KNIT_CANDIDATE = {
    "id": "cand-1",
    "firstName": "Emily",
    "lastName": "Watson",
    "phones": [{"type": "PERSONAL", "phoneNumber": "+1-202"}],
    "emails": [{"type": "PERSONAL", "email": "emily@x.co"}],
    "links": ["https://li/emily"],
    "location": "SF",
}

KNIT_APPLICATION = {
    "info": {
        "id": "app-1",
        "status": "ACTIVE",
        "candidate": KNIT_CANDIDATE,
        "origin": "NOT_SPECIFIED",
        "appliedAt": "2024-11-10T00:00:00Z",
        "updatedAt": "2024-11-16T17:22:09Z",
        "jobId": "job-1",
        "owner": None,
        "creditedTo": None,
    },
    "currentStage": {"id": "s1", "text": "Screen"},
    "interviews": None,
    "rejection": {
        "id": "rj1",
        "text": "Failed Onsite",
        "rejectedAt": "2024-11-16T17:22:09Z",
    },
    "offers": None,
    "attachments": None,
    "questionResponses": None,
}

# Real-world null-heavy variant (Knit's own docs example has nulls here).
KNIT_APPLICATION_SPARSE = {
    "info": {
        "id": "app-2",
        "status": "REJECTED",
        "candidate": {
            "id": "cand-2",
            "firstName": "Leatha",
            "lastName": None,
            "phones": [{"type": "NOT_SPECIFIED", "phoneNumber": "+25 750"}],
            "emails": [{"type": "NOT_SPECIFIED", "email": "l@example.com"}],
            "links": None,
            "location": None,
        },
        "appliedAt": "2024-11-10T00:00:00Z",
        "updatedAt": None,
        "jobId": None,
        "owner": None,
        "creditedTo": None,
    },
    "currentStage": None,
    "interviews": None,
    "rejection": None,
    "offers": None,
    "attachments": None,
    "questionResponses": None,
}


def make_api() -> tuple[KnitCandidatesApi, KnitTransport]:
    transport = KnitTransport(api_key="k", base_url=BASE)
    return KnitCandidatesApi(transport, integration_id="int-1"), transport


async def test_search_candidates_builds_structured_body():
    with respx.mock as mock:
        route = mock.post(f"{BASE}/ats.candidates.search").respond(
            200, json={"success": True, "data": {"candidates": [KNIT_CANDIDATE]}}
        )
        api, transport = make_api()
        results = await api.search_candidates(
            CandidateSearchCriteria(first_name="Emily", email="emily@x.co")
        )
        await transport.aclose()
    sent = json.loads(route.calls[0].request.content)
    assert sent == {"firstName": "Emily", "emails": ["emily@x.co"]}
    assert results[0].first_name == "Emily"
    assert results[0].emails[0].value == "emily@x.co"
    assert results[0].links == ["https://li/emily"]


async def test_list_applications_maps_full_and_sparse():
    with respx.mock as mock:
        mock.get(f"{BASE}/ats.application.list").respond(
            200,
            json={
                "success": True,
                "data": {
                    "applications": [KNIT_APPLICATION, KNIT_APPLICATION_SPARSE],
                    "nextPageToken": "np-1",
                },
            },
        )
        api, transport = make_api()
        page = await api.list_applications()
        await transport.aclose()
    full, sparse = page.items
    assert page.next_page_token == "np-1"
    assert full.id == "app-1" and full.candidate.id == "cand-1"
    assert full.current_stage.name == "Screen"
    assert full.rejection.reason == "Failed Onsite"
    assert full.candidate.phones[0].value == "+1-202"
    assert sparse.candidate.last_name is None
    assert sparse.candidate.links == []
    assert sparse.current_stage is None and sparse.rejection is None


async def test_get_application_requires_both_ids_in_query():
    with respx.mock as mock:
        route = mock.get(f"{BASE}/ats.application.get").respond(
            200, json={"success": True, "data": {"application": KNIT_APPLICATION}}
        )
        api, transport = make_api()
        app_ = await api.get_application("app-1", "cand-1")
        await transport.aclose()
    url = str(route.calls[0].request.url)
    assert "applicationId=app-1" in url and "candidateId=cand-1" in url
    assert app_.id == "app-1" and app_.job_id == "job-1"
