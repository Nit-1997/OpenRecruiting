import json

import httpx

from app.config import get_settings
from app.services.ats_enrichment.cortex_push import (
    push_candidate_evaluation,
    push_candidate_profile,
)


def _url() -> str:
    return f"{get_settings().CORTEX_BACKEND_INTERNAL_URL.rstrip('/')}/api/v1/ingest/direct"


async def test_success_sends_correct_envelope(respx_mock):
    route = respx_mock.post(_url()).mock(return_value=httpx.Response(200, json={"ok": True}))
    ok = await push_candidate_profile(
        org_id="org1", candidate_id="cand1", payload={"skills": ["x"]}
    )
    assert ok is True
    body = json.loads(route.calls[0].request.content)
    assert body["event_type"] == "candidate_profile_enriched"
    assert body["org_id"] == "org1"
    assert body["source_ref"] == {"candidate_id": "cand1"}
    assert body["payload"] == {"skills": ["x"]}
    assert route.calls[0].request.headers["X-Internal-Secret"] is not None


async def test_4xx_returns_false_without_raising(respx_mock):
    respx_mock.post(_url()).mock(return_value=httpx.Response(400, json={"e": 1}))
    assert await push_candidate_profile(org_id="o", candidate_id="c", payload={}) is False


async def test_5xx_returns_false_after_retries(respx_mock):
    respx_mock.post(_url()).mock(return_value=httpx.Response(503))
    assert await push_candidate_profile(org_id="o", candidate_id="c", payload={}) is False


async def test_push_candidate_evaluation_posts_event(respx_mock):
    route = respx_mock.post("http://cortex/api/v1/ingest/direct").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    ok = await push_candidate_evaluation(
        org_id="org-1",
        candidate_id="c1",
        payload={"candidate_id": "c1", "evaluations": []},
        base_url="http://cortex",
        secret="s",
    )
    assert ok is True
    body = json.loads(route.calls[0].request.content)
    assert body["event_type"] == "candidate_evaluation"
    assert body["source_ref"] == {"candidate_id": "c1"}
