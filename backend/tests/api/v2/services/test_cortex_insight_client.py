"""Unit tests for CortexInsightClient — the async httpx proxy that forwards a
confirmed recruiter insight to cortex-backend (POST
{CORTEX_BACKEND_INTERNAL_URL}/ingest/direct, event_type=recruiter_insight).

Mirrors test_cortex_debrief_client.py: happy-path URL/body/secret header; bounded
retry on 5xx then success; 4xx no retry; per-attempt client closed in `finally`;
exhausted retries raise UpstreamServiceError. The httpx layer is mocked so no
network fires.
"""
from __future__ import annotations

import httpx
import pytest

from app.api.v2.core.exceptions import UpstreamServiceError
from app.api.v2.services import cortex_insight_client as mod
from app.api.v2.services.cortex_insight_client import CortexInsightClient

ORG_ID = "00000000-0000-0000-0000-000000000010"
REQ_ID = "00000000-0000-0000-0000-000000000020"
CAND_ID = "00000000-0000-0000-0000-0000000000a1"


class _FakeAsyncClient:
    """Records requests, returns scripted responses, tracks aclose().

    The response queue is SHARED across instances (the production client builds a
    fresh httpx.AsyncClient per retry attempt, so each attempt is a new instance
    drawing from the same scripted queue)."""

    def __init__(self, responses, recorder):
        self._responses = responses
        self._recorder = recorder
        self.closed = False
        recorder["instances"].append(self)

    async def post(self, url, json=None, headers=None):
        self._recorder["calls"].append({"url": url, "json": json, "headers": headers})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def aclose(self):
        self.closed = True


def _resp(status, json_body=None):
    return httpx.Response(
        status,
        json=json_body if json_body is not None else {},
        request=httpx.Request("POST", "http://cortex/ingest/direct"),
    )


def _patch_client(monkeypatch, responses):
    recorder = {"calls": [], "instances": []}

    def _factory(*args, **kwargs):
        return _FakeAsyncClient(responses, recorder)

    monkeypatch.setattr(mod.httpx, "AsyncClient", _factory)
    return recorder


def _client(**over):
    base = dict(base_url="http://cortex", internal_secret="s3cret")
    base.update(over)
    return CortexInsightClient(**base)


@pytest.mark.asyncio
async def test_happy_path_url_body_and_secret_header(monkeypatch):
    rec = _patch_client(monkeypatch, [_resp(200, {"status": "ingested"})])
    client = _client()
    await client.ingest(
        org_id=ORG_ID,
        requisition_id=REQ_ID,
        candidate_id=CAND_ID,
        kind="decision_rationale",
        insight_text="Ada won on system design.",
        triplet=None,
    )
    call = rec["calls"][0]
    assert call["url"].endswith("/ingest/direct")
    assert call["headers"]["X-Internal-Secret"] == "s3cret"

    body = call["json"]
    assert body["event_type"] == "recruiter_insight"
    assert body["org_id"] == ORG_ID
    # The IngestDirectRequest model requires source_ref + timestamp (inherited
    # from IngestRequest); send a valid full body, not just the payload.
    assert body["source_ref"]["requisition_id"] == REQ_ID
    assert body["source_ref"]["candidate_id"] == CAND_ID
    assert isinstance(body["timestamp"], str) and body["timestamp"]

    payload = body["payload"]
    assert payload == {
        "org_id": ORG_ID,
        "requisition_id": REQ_ID,
        "candidate_id": CAND_ID,
        "kind": "decision_rationale",
        "insight_text": "Ada won on system design.",
        "triplet": None,
    }
    assert rec["instances"][0].closed is True


@pytest.mark.asyncio
async def test_triplet_forwarded_in_payload(monkeypatch):
    rec = _patch_client(monkeypatch, [_resp(200, {"status": "ingested"})])
    triplet = {"subject": "PM role", "predicate": "values", "object": "system design"}
    client = _client()
    await client.ingest(
        org_id=ORG_ID,
        requisition_id=REQ_ID,
        candidate_id=None,
        kind="recruiter_preference",
        insight_text="This team weights system design.",
        triplet=triplet,
    )
    payload = rec["calls"][0]["json"]["payload"]
    assert payload["triplet"] == triplet
    assert payload["candidate_id"] is None


@pytest.mark.asyncio
async def test_retries_5xx_then_succeeds(monkeypatch):
    rec = _patch_client(monkeypatch, [_resp(503), _resp(200, {"status": "ingested"})])
    client = _client(max_retries=2, base_backoff_s=0.0)
    await client.ingest(
        org_id=ORG_ID,
        requisition_id=REQ_ID,
        candidate_id=None,
        kind="decision_rationale",
        insight_text="t",
    )
    assert len(rec["calls"]) == 2
    assert rec["instances"][0].closed is True


@pytest.mark.asyncio
async def test_retries_timeout_then_succeeds(monkeypatch):
    err = httpx.ReadTimeout("slow", request=httpx.Request("POST", "http://cortex"))
    rec = _patch_client(monkeypatch, [err, _resp(200, {"status": "ingested"})])
    client = _client(max_retries=2, base_backoff_s=0.0)
    await client.ingest(
        org_id=ORG_ID,
        requisition_id=REQ_ID,
        candidate_id=None,
        kind="decision_rationale",
        insight_text="t",
    )
    assert len(rec["calls"]) == 2


@pytest.mark.asyncio
async def test_4xx_does_not_retry_and_raises(monkeypatch):
    rec = _patch_client(monkeypatch, [_resp(422, {"detail": "bad"})])
    client = _client(max_retries=3, base_backoff_s=0.0)
    with pytest.raises(UpstreamServiceError):
        await client.ingest(
            org_id=ORG_ID,
            requisition_id=REQ_ID,
            candidate_id=None,
            kind="decision_rationale",
            insight_text="t",
        )
    assert len(rec["calls"]) == 1  # no retry on a 4xx
    assert rec["instances"][0].closed is True


@pytest.mark.asyncio
async def test_exhausted_retries_raise_upstream(monkeypatch):
    rec = _patch_client(monkeypatch, [_resp(500), _resp(500), _resp(500)])
    client = _client(max_retries=3, base_backoff_s=0.0)
    with pytest.raises(UpstreamServiceError):
        await client.ingest(
            org_id=ORG_ID,
            requisition_id=REQ_ID,
            candidate_id=None,
            kind="decision_rationale",
            insight_text="t",
        )
    assert all(inst.closed for inst in rec["instances"])


@pytest.mark.asyncio
async def test_client_closed_even_on_connect_error(monkeypatch):
    err = httpx.ConnectError("refused", request=httpx.Request("POST", "http://cortex"))
    rec = _patch_client(monkeypatch, [err, err])
    client = _client(max_retries=2, base_backoff_s=0.0)
    with pytest.raises(UpstreamServiceError):
        await client.ingest(
            org_id=ORG_ID,
            requisition_id=REQ_ID,
            candidate_id=None,
            kind="decision_rationale",
            insight_text="t",
        )
    assert all(inst.closed for inst in rec["instances"])


@pytest.mark.asyncio
async def test_honors_retry_after_header(monkeypatch):
    """A 5xx with a numeric Retry-After header sleeps that many seconds before the
    retry (not the linear backoff). The second attempt succeeds."""
    rec = _patch_client(
        monkeypatch,
        [
            _resp(503, {"status": "error"}),
            _resp(200, {"status": "ingested"}),
        ],
    )
    # Inject the Retry-After header on the first (503) response.
    rec["instances"]  # ensure recorder exists
    slept: list[float] = []

    async def _fake_sleep(secs):
        slept.append(secs)

    monkeypatch.setattr(mod.asyncio, "sleep", _fake_sleep)

    # Patch the first response object to carry Retry-After.
    orig_post = _FakeAsyncClient.post

    async def _post(self, url, json=None, headers=None):
        resp = await orig_post(self, url, json=json, headers=headers)
        if resp.status_code == 503:
            resp.headers["Retry-After"] = "2"
        return resp

    monkeypatch.setattr(_FakeAsyncClient, "post", _post)

    client = _client(max_retries=2, base_backoff_s=0.5)
    await client.ingest(
        org_id=ORG_ID,
        requisition_id=REQ_ID,
        candidate_id=None,
        kind="decision_rationale",
        insight_text="t",
    )
    assert slept == [2.0]  # honored Retry-After, not 0.5 linear backoff


@pytest.mark.asyncio
async def test_client_close_failure_is_swallowed(monkeypatch):
    """A failure to close the per-attempt client must not mask the real result."""
    rec = _patch_client(monkeypatch, [_resp(200, {"status": "ingested"})])

    async def _boom(self):
        self.closed = True
        raise RuntimeError("close failed")

    monkeypatch.setattr(_FakeAsyncClient, "aclose", _boom)

    client = _client()
    # Must NOT raise despite the close error.
    await client.ingest(
        org_id=ORG_ID,
        requisition_id=REQ_ID,
        candidate_id=None,
        kind="decision_rationale",
        insight_text="t",
    )
    assert rec["instances"][0].closed is True


def test_parse_retry_after_edge_cases():
    assert mod._parse_retry_after(None) is None
    assert mod._parse_retry_after("") is None
    assert mod._parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT") is None
    assert mod._parse_retry_after("-3") is None
    assert mod._parse_retry_after("5") == 5.0


@pytest.mark.asyncio
async def test_default_secret_comes_from_cortex_internal_secret_setting(monkeypatch):
    """The OUTBOUND secret to cortex-backend is the DEDICATED CORTEX_INTERNAL_SECRET,
    NOT the inbound INTERNAL_API_SECRET used for inbound internal callers."""
    rec = _patch_client(monkeypatch, [_resp(200, {"status": "ingested"})])

    settings = mod.get_settings()
    monkeypatch.setattr(settings, "CORTEX_INTERNAL_SECRET", "cortex-outbound-secret")
    monkeypatch.setattr(settings, "INTERNAL_API_SECRET", "inbound-secret")

    client = CortexInsightClient(base_url="http://cortex")
    await client.ingest(
        org_id=ORG_ID,
        requisition_id=REQ_ID,
        candidate_id=None,
        kind="decision_rationale",
        insight_text="t",
    )

    sent = rec["calls"][0]["headers"]["X-Internal-Secret"]
    assert sent == "cortex-outbound-secret"
    assert sent != "inbound-secret"
