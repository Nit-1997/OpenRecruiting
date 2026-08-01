"""Public Recall-bot voice-status endpoint (app/api/v2/routers/public_voice.py).

The voice-agent camera page polls this to know when to connect the agent.
Replaces the retired v1 GET /api/v1/public/voice/status/{token}, whose removal
left the page polling a 404 → stuck on its dormant view → agent never went live.
"""
import httpx

from tests.helpers.supabase_mocks import rest_url

ROOT = "/api/v2/public/voice/status"
# voice_session_token is a uuid column — use a real uuid for the DB-hitting paths.
TOKEN = "11111111-1111-4111-8111-111111111111"


def test_returns_bot_voice_status_for_known_token(unauthed_client, respx_mock):
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{"voice_session_status": "activating"}])
    )
    resp = unauthed_client.get(f"{ROOT}/{TOKEN}")
    assert resp.status_code == 200
    assert resp.json() == {"status": "activating"}


def test_unknown_token_returns_dormant(unauthed_client, respx_mock):
    respx_mock.get(rest_url("recall_bots")).mock(return_value=httpx.Response(200, json=[]))
    resp = unauthed_client.get(f"{ROOT}/{TOKEN}")
    assert resp.status_code == 200
    assert resp.json() == {"status": "dormant"}


def test_null_status_falls_back_to_dormant(unauthed_client, respx_mock):
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{"voice_session_status": None}])
    )
    resp = unauthed_client.get(f"{ROOT}/{TOKEN}")
    assert resp.status_code == 200
    assert resp.json() == {"status": "dormant"}


def test_malformed_non_uuid_token_returns_dormant_without_db(unauthed_client):
    # A non-uuid token can't match the uuid column; must short-circuit to dormant
    # (no DB call) instead of 500'ing on a 22P02 cast error. No respx mock needed
    # precisely because no Supabase request should be made.
    resp = unauthed_client.get(f"{ROOT}/not-a-uuid")
    assert resp.status_code == 200
    assert resp.json() == {"status": "dormant"}
