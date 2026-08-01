"""Unit tests for CortexDebriefClient — the async httpx proxy to the Cortex
debrief skill (POST {CORTEX_BACKEND_INTERNAL_URL}/api/v1/debrief).

Asserts: happy-path payload + headers; bounded retry on 5xx then success;
exhausted retries raise UpstreamServiceError; the per-call client is always
closed (no module-global loop-bound client). The httpx layer is mocked via a
fake transport / monkeypatched AsyncClient so no network fires.
"""
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.api.v2.core.exceptions import UpstreamServiceError
from app.api.v2.services import cortex_debrief_client as mod
from app.api.v2.services.cortex_debrief_client import CortexDebriefClient

ORG_ID = "00000000-0000-0000-0000-000000000010"
REQ_ID = "00000000-0000-0000-0000-000000000020"
CANDS = ["00000000-0000-0000-0000-0000000000a1", "00000000-0000-0000-0000-0000000000a2"]


class _FakeAsyncClient:
    """Records requests, returns scripted responses, tracks aclose().

    The response queue is SHARED across instances (it models the sequence of
    server replies). The production client builds a fresh httpx.AsyncClient per
    retry attempt, so each attempt is a new _FakeAsyncClient — but they must all
    draw from the same scripted queue, not a per-instance copy."""

    def __init__(self, responses, recorder):
        self._responses = responses  # shared queue (mutated across instances)
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
        request=httpx.Request("POST", "http://cortex/api/v1/debrief"),
    )


def _patch_client(monkeypatch, responses):
    recorder = {"calls": [], "instances": []}

    def _factory(*args, **kwargs):
        return _FakeAsyncClient(responses, recorder)

    monkeypatch.setattr(mod.httpx, "AsyncClient", _factory)
    return recorder


def _packet(**over):
    base = {"id": "p1", "requisition_id": REQ_ID, "verdict": "hire", "status": "fresh"}
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_happy_path_payload_and_headers(monkeypatch):
    rec = _patch_client(monkeypatch, [_resp(200, _packet())])
    client = CortexDebriefClient(base_url="http://cortex", internal_secret="s3cret")
    out = await client.generate(org_id=ORG_ID, requisition_id=REQ_ID, candidate_ids=CANDS)
    assert out["verdict"] == "hire"
    call = rec["calls"][0]
    assert call["url"].endswith("/api/v1/debrief")
    assert call["json"] == {"org_id": ORG_ID, "requisition_id": REQ_ID, "candidate_ids": CANDS}
    assert call["headers"]["X-Internal-Secret"] == "s3cret"
    assert rec["instances"][0].closed is True


@pytest.mark.asyncio
async def test_retries_5xx_then_succeeds(monkeypatch):
    rec = _patch_client(monkeypatch, [_resp(503), _resp(200, _packet())])
    client = CortexDebriefClient(
        base_url="http://cortex", internal_secret="s", max_retries=2, base_backoff_s=0.0
    )
    out = await client.generate(org_id=ORG_ID, requisition_id=REQ_ID, candidate_ids=CANDS)
    assert out["status"] == "fresh"
    assert len(rec["calls"]) == 2
    assert rec["instances"][0].closed is True


@pytest.mark.asyncio
async def test_retries_timeout_then_succeeds(monkeypatch):
    err = httpx.ReadTimeout("slow", request=httpx.Request("POST", "http://cortex"))
    rec = _patch_client(monkeypatch, [err, _resp(200, _packet())])
    client = CortexDebriefClient(
        base_url="http://cortex", internal_secret="s", max_retries=2, base_backoff_s=0.0
    )
    out = await client.generate(org_id=ORG_ID, requisition_id=REQ_ID, candidate_ids=CANDS)
    assert out["verdict"] == "hire"
    assert len(rec["calls"]) == 2


@pytest.mark.asyncio
async def test_exhausted_retries_raise_upstream(monkeypatch):
    rec = _patch_client(monkeypatch, [_resp(500), _resp(500), _resp(500)])
    client = CortexDebriefClient(
        base_url="http://cortex", internal_secret="s", max_retries=3, base_backoff_s=0.0
    )
    with pytest.raises(UpstreamServiceError):
        await client.generate(org_id=ORG_ID, requisition_id=REQ_ID, candidate_ids=CANDS)
    # client closed on every attempt
    assert all(inst.closed for inst in rec["instances"])


@pytest.mark.asyncio
async def test_4xx_does_not_retry_and_raises(monkeypatch):
    rec = _patch_client(monkeypatch, [_resp(422, {"detail": "bad"})])
    client = CortexDebriefClient(
        base_url="http://cortex", internal_secret="s", max_retries=3, base_backoff_s=0.0
    )
    with pytest.raises(UpstreamServiceError):
        await client.generate(org_id=ORG_ID, requisition_id=REQ_ID, candidate_ids=CANDS)
    assert len(rec["calls"]) == 1  # no retry on a 4xx


@pytest.mark.asyncio
async def test_client_closed_even_on_exception(monkeypatch):
    err = httpx.ConnectError("refused", request=httpx.Request("POST", "http://cortex"))
    rec = _patch_client(monkeypatch, [err, err])
    client = CortexDebriefClient(
        base_url="http://cortex", internal_secret="s", max_retries=2, base_backoff_s=0.0
    )
    with pytest.raises(UpstreamServiceError):
        await client.generate(org_id=ORG_ID, requisition_id=REQ_ID, candidate_ids=CANDS)
    assert all(inst.closed for inst in rec["instances"])


@pytest.mark.asyncio
async def test_default_secret_comes_from_cortex_internal_secret_setting(monkeypatch):
    """FIX 3: the OUTBOUND secret to cortex-backend is the DEDICATED
    CORTEX_INTERNAL_SECRET, NOT the inbound INTERNAL_API_SECRET (which is shared
    with the slack agent and validated by a different service)."""
    rec = _patch_client(monkeypatch, [_resp(200, _packet())])

    settings = mod.get_settings()
    monkeypatch.setattr(settings, "CORTEX_INTERNAL_SECRET", "cortex-outbound-secret")
    monkeypatch.setattr(settings, "INTERNAL_API_SECRET", "inbound-slack-secret")

    # No internal_secret override → must fall back to CORTEX_INTERNAL_SECRET.
    client = CortexDebriefClient(base_url="http://cortex")
    await client.generate(org_id=ORG_ID, requisition_id=REQ_ID, candidate_ids=CANDS)

    sent = rec["calls"][0]["headers"]["X-Internal-Secret"]
    assert sent == "cortex-outbound-secret"
    assert sent != "inbound-slack-secret"


@pytest.mark.asyncio
async def test_payload_shape_unchanged(monkeypatch):
    """FIX 3: the request body stays {org_id, requisition_id, candidate_ids}."""
    rec = _patch_client(monkeypatch, [_resp(200, _packet())])
    client = CortexDebriefClient(base_url="http://cortex", internal_secret="s")
    await client.generate(org_id=ORG_ID, requisition_id=REQ_ID, candidate_ids=CANDS)
    assert rec["calls"][0]["json"] == {
        "org_id": ORG_ID,
        "requisition_id": REQ_ID,
        "candidate_ids": CANDS,
    }
