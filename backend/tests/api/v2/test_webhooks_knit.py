"""POST /api/v2/webhooks/knit — signature gate, eventId idempotency, ack shape."""

import base64
import hashlib
import hmac as hmac_lib
import json

from tests.helpers.supabase_mocks import rest_url

URL = "/api/v2/webhooks/knit"
KEY = "test-knit-key"  # conftest KNIT_API_KEY

EVENT = {
    "eventId": "evt-1",
    "eventType": "sync.heartbeat",
    "eventData": {},
    "syncType": "delta_sync",
    "syncDataType": "ats_jobs",
    "syncJobId": "sj-1",
    "syncRunId": "sr-1",
    "triggeredAt": "1765500000000",
    "recordId": "sr-1",
}


def sign(body: bytes) -> str:
    digest = hmac_lib.new(KEY.encode(), body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def post_event(client, payload: dict, signature: str | None = None):
    raw = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Knit-Signature": signature if signature is not None else sign(raw),
    }
    return client.post(URL, content=raw, headers=headers)


def test_valid_event_persisted_pending(unauthed_client, respx_mock):
    """Receiver persists + acks WITHOUT touching processed_at — pending rows
    are the drainer's work-queue contract (phase 2)."""
    insert_route = respx_mock.post(rest_url("ats_webhook_events")).respond(
        201, json=[{"event_id": "evt-1"}]
    )
    resp = post_event(unauthed_client, EVENT)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["message"] == "received"
    assert body["eventId"] == "evt-1"
    sent = json.loads(insert_route.calls[0].request.content)
    assert "processed_at" not in sent


def test_duplicate_event_acked_without_reprocessing(unauthed_client, respx_mock):
    respx_mock.post(rest_url("ats_webhook_events")).respond(
        409,
        json={
            "code": "23505",
            "message": 'duplicate key value violates unique constraint "ats_webhook_events_pkey"',
        },
    )
    resp = post_event(unauthed_client, EVENT)
    assert resp.status_code == 200
    assert resp.json()["message"] == "duplicate"


def test_bad_signature_401(unauthed_client, respx_mock):
    resp = post_event(unauthed_client, EVENT, signature="forged")
    assert resp.status_code == 401


def test_missing_event_id_400(unauthed_client, respx_mock):
    payload = {k: v for k, v in EVENT.items() if k != "eventId"}
    resp = post_event(unauthed_client, payload)
    assert resp.status_code == 400


def test_integration_id_header_persisted(unauthed_client, respx_mock):
    route = respx_mock.post(rest_url("ats_webhook_events")).respond(
        201, json=[{"event_id": "evt-9"}]
    )
    raw = json.dumps({**EVENT, "eventId": "evt-9"}).encode()
    resp = unauthed_client.post(
        URL,
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Knit-Signature": sign(raw),
            "X-Knit-Integration-Id": "int-1",
        },
    )
    assert resp.status_code == 200
    sent = json.loads(route.calls[0].request.content)
    assert sent["integration_id"] == "int-1"
