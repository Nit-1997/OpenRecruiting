import time
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v2.routers import webhooks_slack as ws
from app.config import get_settings

SIGNING_SECRET = "test-signing-secret"


def _sign(body: bytes, ts: str | None = None) -> dict:
    ts = ts or str(int(time.time()))
    sig = "v0=" + hmac.new(
        SIGNING_SECRET.encode(), f"v0:{ts}:{body.decode()}".encode(), hashlib.sha256
    ).hexdigest()
    return {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig}


@pytest.fixture
def signing(monkeypatch):
    monkeypatch.setattr(get_settings(), "SLACK_SIGNING_SECRET", SIGNING_SECRET, raising=False)
    return SIGNING_SECRET


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def test_verify_slack_signature_valid_and_invalid(monkeypatch):
    monkeypatch.setattr(get_settings(), "SLACK_SIGNING_SECRET", SIGNING_SECRET, raising=False)

    body = b'{"hello":"world"}'
    ts = str(int(time.time()))
    good = "v0=" + hmac.new(SIGNING_SECRET.encode(), f"v0:{ts}:{body.decode()}".encode(), hashlib.sha256).hexdigest()

    assert ws.verify_slack_signature(ts, body, good) is True
    assert ws.verify_slack_signature(ts, body, "v0=deadbeef") is False
    old_ts = str(int(time.time()) - 10_000)
    assert ws.verify_slack_signature(old_ts, body, good) is False


def test_verify_signature_no_secret_false(monkeypatch):
    monkeypatch.setattr(get_settings(), "SLACK_SIGNING_SECRET", "", raising=False)
    assert ws.verify_slack_signature("123", b"x", "v0=abc") is False


def test_verify_signature_missing_ts_or_sig_false(monkeypatch):
    monkeypatch.setattr(get_settings(), "SLACK_SIGNING_SECRET", SIGNING_SECRET, raising=False)
    assert ws.verify_slack_signature("", b"x", "v0=abc") is False
    assert ws.verify_slack_signature("123", b"x", "") is False


def test_verify_signature_non_int_timestamp_false(monkeypatch):
    monkeypatch.setattr(get_settings(), "SLACK_SIGNING_SECRET", SIGNING_SECRET, raising=False)
    assert ws.verify_slack_signature("not-a-number", b"x", "v0=abc") is False


# ---------------------------------------------------------------------------
# /slack/events route dispatch
# ---------------------------------------------------------------------------

def test_slack_events_url_verification_challenge(unauthed_client):
    resp = unauthed_client.post(
        "/api/v2/webhooks/slack/events",
        json={"type": "url_verification", "challenge": "abc123"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"challenge": "abc123"}


def test_slack_events_invalid_json_400(unauthed_client):
    resp = unauthed_client.post(
        "/api/v2/webhooks/slack/events",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def test_slack_events_bad_signature_401(unauthed_client, signing):
    body = json.dumps({"type": "event_callback", "event": {"type": "message"}}).encode()
    resp = unauthed_client.post(
        "/api/v2/webhooks/slack/events",
        content=body,
        headers={"X-Slack-Request-Timestamp": str(int(time.time())), "X-Slack-Signature": "v0=bad"},
    )
    assert resp.status_code == 401


def test_slack_events_im_message_dispatches_message_handler(unauthed_client, signing, monkeypatch):
    captured = {}

    async def fake_handler(event, team_id):
        captured["event"] = event
        captured["team_id"] = team_id

    monkeypatch.setattr(ws, "handle_message_event", fake_handler)
    body = json.dumps({
        "type": "event_callback", "team_id": "T1",
        "event": {"type": "message", "channel_type": "im", "user": "U1", "text": "hi"},
    }).encode()
    resp = unauthed_client.post("/api/v2/webhooks/slack/events", content=body, headers=_sign(body))
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert captured["team_id"] == "T1"
    assert captured["event"]["text"] == "hi"


def test_slack_events_app_mention_dispatches(unauthed_client, signing, monkeypatch):
    called = {"n": 0}

    async def fake_handler(event, team_id):
        called["n"] += 1

    monkeypatch.setattr(ws, "handle_message_event", fake_handler)
    body = json.dumps({
        "type": "event_callback", "team_id": "T1",
        "event": {"type": "app_mention", "user": "U1", "text": "hey"},
    }).encode()
    resp = unauthed_client.post("/api/v2/webhooks/slack/events", content=body, headers=_sign(body))
    assert resp.status_code == 200
    assert called["n"] == 1


def test_slack_events_app_home_opened_dispatches(unauthed_client, signing, monkeypatch):
    called = {"n": 0}

    async def fake_handler(event, team_id):
        called["n"] += 1

    monkeypatch.setattr(ws, "handle_app_home_opened", fake_handler)
    body = json.dumps({
        "type": "event_callback", "team_id": "T1",
        "event": {"type": "app_home_opened", "user": "U1"},
    }).encode()
    resp = unauthed_client.post("/api/v2/webhooks/slack/events", content=body, headers=_sign(body))
    assert resp.status_code == 200
    assert called["n"] == 1


def test_slack_events_unknown_event_no_dispatch(unauthed_client, signing, monkeypatch):
    msg_called = {"n": 0}
    monkeypatch.setattr(ws, "handle_message_event", lambda *a, **k: msg_called.__setitem__("n", msg_called["n"] + 1))
    body = json.dumps({
        "type": "event_callback", "team_id": "T1",
        "event": {"type": "reaction_added", "user": "U1"},
    }).encode()
    resp = unauthed_client.post("/api/v2/webhooks/slack/events", content=body, headers=_sign(body))
    assert resp.status_code == 200
    assert msg_called["n"] == 0


# ---------------------------------------------------------------------------
# /slack/interactions route dispatch
# ---------------------------------------------------------------------------

def test_slack_interactions_bad_signature_401(unauthed_client, signing):
    body = b"payload=%7B%7D"
    resp = unauthed_client.post(
        "/api/v2/webhooks/slack/interactions",
        content=body,
        headers={"X-Slack-Request-Timestamp": str(int(time.time())), "X-Slack-Signature": "v0=bad",
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 401


def test_slack_interactions_block_action_dispatches(unauthed_client, signing, monkeypatch):
    captured = {}

    async def fake_handler(payload):
        captured["payload"] = payload

    monkeypatch.setattr(ws, "handle_block_action", fake_handler)
    payload = json.dumps({"type": "block_actions", "actions": [{"action_id": "x"}]})
    body = f"payload={payload}".encode()
    resp = unauthed_client.post(
        "/api/v2/webhooks/slack/interactions", content=body,
        headers={**_sign(body), "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    assert captured["payload"]["type"] == "block_actions"


def test_slack_interactions_empty_payload_ok(unauthed_client, signing):
    body = b"payload="
    resp = unauthed_client.post(
        "/api/v2/webhooks/slack/interactions", content=body,
        headers={**_sign(body), "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_slack_interactions_bad_json_payload_ok(unauthed_client, signing):
    body = b"payload=not-json"
    resp = unauthed_client.post(
        "/api/v2/webhooks/slack/interactions", content=body,
        headers={**_sign(body), "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_slack_interactions_view_submission_no_crash(unauthed_client, signing):
    payload = json.dumps({"type": "view_submission", "view": {"callback_id": "other_modal"}})
    body = f"payload={payload}".encode()
    resp = unauthed_client.post(
        "/api/v2/webhooks/slack/interactions", content=body,
        headers={**_sign(body), "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# _get_effective_slack_features
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_effective_features_no_org_returns_defaults():
    out = await ws._get_effective_slack_features(None, {})
    assert out == ws._DEFAULT_SLACK_FEATURES


@pytest.mark.asyncio
async def test_effective_features_user_overrides_org():
    # User flags override org defaults; no org_id → org lookup skipped.
    out = await ws._get_effective_slack_features(
        None, {"user_slack_features": {"assistant_write": True}}
    )
    assert out["assistant_write"] is True


@pytest.mark.asyncio
async def test_effective_features_org_lookup(monkeypatch, respx_mock):
    import httpx
    from tests.helpers.supabase_mocks import rest_url
    respx_mock.get(rest_url("organizations")).mock(
        return_value=httpx.Response(200, json=[{"slack_features": {"assistant_read": True}}])
    )
    out = await ws._get_effective_slack_features("org-1", {})
    assert out["assistant_read"] is True


# ---------------------------------------------------------------------------
# handle_message_event
# ---------------------------------------------------------------------------

def _slack_svc(monkeypatch):
    svc = MagicMock()
    svc.get_bot_token_for_team = AsyncMock(return_value="xoxb")
    svc.get_connection = AsyncMock()
    svc.send_message = AsyncMock(return_value={"ok": True, "ts": "1.1"})
    svc.update_message = AsyncMock(return_value={"ok": True})
    svc.publish_home_tab = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(ws, "get_slack_service", lambda: svc)
    return svc


@pytest.mark.asyncio
async def test_handle_message_event_bot_message_ignored(monkeypatch):
    svc = _slack_svc(monkeypatch)
    await ws.handle_message_event({"bot_id": "B1", "user": "U1", "channel": "C1"}, "T1")
    svc.get_bot_token_for_team.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_event_missing_user_or_channel(monkeypatch):
    svc = _slack_svc(monkeypatch)
    await ws.handle_message_event({"type": "message"}, "T1")
    svc.get_bot_token_for_team.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_event_no_installation(monkeypatch):
    svc = _slack_svc(monkeypatch)
    svc.get_bot_token_for_team = AsyncMock(side_effect=ValueError("none"))
    await ws.handle_message_event({"user": "U1", "channel": "C1", "text": "hi"}, "T1")
    svc.get_connection.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_event_no_connection_sends_link_prompt(monkeypatch):
    svc = _slack_svc(monkeypatch)
    svc.get_connection = AsyncMock(return_value=None)
    await ws.handle_message_event({"user": "U1", "channel": "C1", "text": "hi"}, "T1")
    svc.send_message.assert_awaited()
    # The not-linked prompt is sent.
    assert "isn't connected" in svc.send_message.call_args.args[2] or "isn't linked" in str(svc.send_message.call_args)


@pytest.mark.asyncio
async def test_handle_message_event_no_agent_mode_warm_message(monkeypatch):
    svc = _slack_svc(monkeypatch)
    svc.get_connection = AsyncMock(return_value={"organization_id": "o1", "profile_id": "p1"})
    monkeypatch.setattr(ws, "_get_effective_slack_features",
                        AsyncMock(return_value={"assistant_read": False, "assistant_write": False}))
    ws._warm_message_cooldown.clear()
    await ws.handle_message_event({"user": "U-warm", "channel": "C1", "text": "hi"}, "T1")
    # Warm "coming soon" message sent once.
    svc.send_message.assert_awaited()
    assert "U-warm" in ws._warm_message_cooldown


@pytest.mark.asyncio
async def test_handle_message_event_warm_message_cooldown_suppressed(monkeypatch):
    svc = _slack_svc(monkeypatch)
    svc.get_connection = AsyncMock(return_value={"organization_id": "o1", "profile_id": "p1"})
    monkeypatch.setattr(ws, "_get_effective_slack_features",
                        AsyncMock(return_value={"assistant_read": False, "assistant_write": False}))
    ws._warm_message_cooldown.clear()
    ws._warm_message_cooldown["U-cool"] = time.time()
    await ws.handle_message_event({"user": "U-cool", "channel": "C1", "text": "hi"}, "T1")
    svc.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_message_event_clear_session(monkeypatch, respx_mock):
    import httpx
    from tests.helpers.supabase_mocks import rest_url
    svc = _slack_svc(monkeypatch)
    svc.get_connection = AsyncMock(return_value={"organization_id": "o1", "profile_id": "p1"})
    monkeypatch.setattr(ws, "_get_effective_slack_features",
                        AsyncMock(return_value={"assistant_read": True, "assistant_write": True}))
    respx_mock.delete(rest_url("agent_conversations")).mock(return_value=httpx.Response(200, json=[]))
    await ws.handle_message_event({"user": "U1", "channel": "C1", "text": "/clear"}, "T1")
    # The "session cleared" confirmation is sent.
    svc.send_message.assert_awaited()
    assert "cleared" in str(svc.send_message.call_args).lower()


@pytest.mark.asyncio
async def test_handle_message_event_full_mode_posts_to_agent(monkeypatch):
    svc = _slack_svc(monkeypatch)
    svc.get_connection = AsyncMock(return_value={"organization_id": "o1", "profile_id": "p1"})
    monkeypatch.setattr(ws, "_get_effective_slack_features",
                        AsyncMock(return_value={"assistant_read": True, "assistant_write": True}))

    posted = {}

    class FakeClient:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, json=None):
            posted["url"] = url
            posted["json"] = json
            return MagicMock()

    monkeypatch.setattr(ws.httpx, "AsyncClient", FakeClient)
    await ws.handle_message_event({"user": "U1", "channel": "C1", "text": "find candidates"}, "T1")
    assert posted["url"].endswith("/run")
    assert posted["json"]["mode"] == "full"
    assert posted["json"]["user_message"] == "find candidates"


@pytest.mark.asyncio
async def test_handle_message_event_agent_failure_updates_thinking(monkeypatch):
    svc = _slack_svc(monkeypatch)
    svc.get_connection = AsyncMock(return_value={"organization_id": "o1", "profile_id": "p1"})
    svc.send_message = AsyncMock(return_value={"ok": True, "ts": "TS-THINK"})
    monkeypatch.setattr(ws, "_get_effective_slack_features",
                        AsyncMock(return_value={"assistant_read": True, "assistant_write": True}))

    class FakeClient:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, json=None):
            raise RuntimeError("agent down")

    monkeypatch.setattr(ws.httpx, "AsyncClient", FakeClient)
    await ws.handle_message_event({"user": "U1", "channel": "C1", "text": "go"}, "T1")
    # On failure with a thinking ts, the thinking message is updated with the error.
    svc.update_message.assert_awaited()


# ---------------------------------------------------------------------------
# handle_app_home_opened
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_app_home_opened_no_user(monkeypatch):
    svc = _slack_svc(monkeypatch)
    await ws.handle_app_home_opened({}, "T1")
    svc.get_bot_token_for_team.assert_not_called()


@pytest.mark.asyncio
async def test_handle_app_home_opened_no_install(monkeypatch):
    svc = _slack_svc(monkeypatch)
    svc.get_bot_token_for_team = AsyncMock(side_effect=ValueError("none"))
    await ws.handle_app_home_opened({"user": "U1"}, "T1")
    svc.publish_home_tab.assert_not_called()


@pytest.mark.asyncio
async def test_handle_app_home_opened_publishes(monkeypatch, respx_mock):
    import httpx
    from tests.helpers.supabase_mocks import rest_url
    svc = _slack_svc(monkeypatch)
    svc.get_connection = AsyncMock(return_value={"organization_id": "o1"})
    respx_mock.get(rest_url("organizations")).mock(
        return_value=httpx.Response(200, json=[{"name": "Acme"}])
    )
    await ws.handle_app_home_opened({"user": "U1"}, "T1")
    svc.publish_home_tab.assert_awaited_once()


# ---------------------------------------------------------------------------
# _get_action_label
# ---------------------------------------------------------------------------

def test_get_action_label_variants():
    assert ws._get_action_label({"text": {"text": "Hello"}}) == "Hello"
    assert ws._get_action_label({"text": "Plain"}) == "Plain"
    assert ws._get_action_label({}) == ""


# ---------------------------------------------------------------------------
# handle_block_action / _handle_block_action_inner
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_block_action_swallows_exceptions(monkeypatch):
    async def boom(payload):
        raise RuntimeError("inner crash")
    monkeypatch.setattr(ws, "_handle_block_action_inner", boom)
    # Must not raise — the wrapper logs and swallows.
    await ws.handle_block_action({"actions": [{"action_id": "x"}]})


@pytest.mark.asyncio
async def test_block_action_inner_no_actions_noop(monkeypatch):
    svc = _slack_svc(monkeypatch)
    await ws._handle_block_action_inner({"actions": []})
    svc.get_bot_token_for_team.assert_not_called()


@pytest.mark.asyncio
async def test_block_action_inner_url_button_noop(monkeypatch):
    svc = _slack_svc(monkeypatch)
    await ws._handle_block_action_inner({"actions": [{"action_id": "view_in_app"}]})
    svc.get_bot_token_for_team.assert_not_called()


@pytest.mark.asyncio
async def test_block_action_inner_view_req_prefix_noop(monkeypatch):
    svc = _slack_svc(monkeypatch)
    await ws._handle_block_action_inner({"actions": [{"action_id": "view_req_123"}]})
    svc.get_bot_token_for_team.assert_not_called()


@pytest.mark.asyncio
async def test_block_action_inner_missing_fields_noop(monkeypatch):
    svc = _slack_svc(monkeypatch)
    # No channel / team → bails before bot token lookup.
    await ws._handle_block_action_inner({
        "actions": [{"action_id": "select_entity_x", "value": "{}"}],
        "user": {"id": "U1"},
    })
    svc.get_bot_token_for_team.assert_not_called()


@pytest.mark.asyncio
async def test_block_action_inner_confirm_no_with_response_url(monkeypatch):
    svc = _slack_svc(monkeypatch)
    posted = {}

    class FakeClient:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, json=None):
            posted["url"] = url
            posted["json"] = json
            return MagicMock()

    monkeypatch.setattr(ws.httpx, "AsyncClient", FakeClient)
    await ws._handle_block_action_inner({
        "actions": [{"action_id": "confirm_no", "value": "{}"}],
        "user": {"id": "U1"}, "channel": {"id": "C1"}, "team": {"id": "T1"},
        "response_url": "https://hooks.slack.com/r/abc",
    })
    assert posted["json"]["text"] == "Cancelled."
    # Did not proceed to bot token / agent.
    svc.get_bot_token_for_team.assert_not_called()


@pytest.mark.asyncio
async def test_block_action_inner_no_connection_noop(monkeypatch):
    svc = _slack_svc(monkeypatch)
    svc.get_connection = AsyncMock(return_value=None)
    await ws._handle_block_action_inner({
        "actions": [{"action_id": "select_entity_x", "value": "{\"id\": \"r1\"}"}],
        "user": {"id": "U1"}, "channel": {"id": "C1"}, "team": {"id": "T1"},
    })
    svc.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_block_action_inner_select_entity_resumes_agent(monkeypatch):
    svc = _slack_svc(monkeypatch)
    svc.get_connection = AsyncMock(return_value={"organization_id": "o1", "profile_id": "p1"})
    svc.send_message = AsyncMock(return_value={"ok": True, "ts": "TS"})
    monkeypatch.setattr(ws, "_get_effective_slack_features",
                        AsyncMock(return_value={"assistant_read": True, "assistant_write": True}))

    posted = {}

    class FakeClient:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, json=None):
            # First call is the response_url update; final call is the agent.
            posted.setdefault("calls", []).append((url, json))
            return MagicMock()

    monkeypatch.setattr(ws.httpx, "AsyncClient", FakeClient)
    await ws._handle_block_action_inner({
        "actions": [{"action_id": "select_entity_req", "value": "{\"id\": \"r1\"}",
                     "text": {"text": "Senior Engineer"}}],
        "user": {"id": "U1"}, "channel": {"id": "C1"}, "team": {"id": "T1"},
        "response_url": "https://hooks.slack.com/r/abc",
    })
    # Last posted call should be to /resume (select_entity is a resume action).
    agent_call = posted["calls"][-1]
    assert agent_call[0].endswith("/resume")
    assert "DISAMBIGUATION_RESPONSE" in agent_call[1]["user_response"]


@pytest.mark.asyncio
async def test_block_action_inner_confirm_yes_runs_agent(monkeypatch):
    svc = _slack_svc(monkeypatch)
    svc.get_connection = AsyncMock(return_value={"organization_id": "o1", "profile_id": "p1"})
    svc.send_message = AsyncMock(return_value={"ok": True, "ts": "TS"})
    monkeypatch.setattr(ws, "_get_effective_slack_features",
                        AsyncMock(return_value={"assistant_read": True, "assistant_write": True}))

    posted = {}

    class FakeClient:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, json=None):
            posted.setdefault("calls", []).append((url, json))
            return MagicMock()

    monkeypatch.setattr(ws.httpx, "AsyncClient", FakeClient)
    await ws._handle_block_action_inner({
        "actions": [{"action_id": "confirm_yes", "value": "{\"x\": 1}", "text": "Yes"}],
        "user": {"id": "U1"}, "channel": {"id": "C1"}, "team": {"id": "T1"},
    })
    agent_call = posted["calls"][-1]
    assert agent_call[0].endswith("/resume")
    assert "CONFIRMED_ACTION" in agent_call[1]["user_response"]


@pytest.mark.asyncio
async def test_block_action_inner_no_mode_updates_thinking(monkeypatch):
    svc = _slack_svc(monkeypatch)
    svc.get_connection = AsyncMock(return_value={"organization_id": "o1", "profile_id": "p1"})
    svc.send_message = AsyncMock(return_value={"ok": True, "ts": "TS"})
    monkeypatch.setattr(ws, "_get_effective_slack_features",
                        AsyncMock(return_value={"assistant_read": False, "assistant_write": False}))
    await ws._handle_block_action_inner({
        "actions": [{"action_id": "generic_select", "value": "{}", "text": "Pick"}],
        "user": {"id": "U1"}, "channel": {"id": "C1"}, "team": {"id": "T1"},
    })
    # Assistant disabled → updates thinking message and returns; never posts to agent.
    svc.update_message.assert_awaited()


@pytest.mark.asyncio
async def test_block_action_inner_team_from_user_team_id(monkeypatch):
    """team_id derived from user.team_id when no top-level team/channel-team is present."""
    svc = _slack_svc(monkeypatch)
    svc.get_connection = AsyncMock(return_value={"organization_id": "o1", "profile_id": "p1"})
    svc.send_message = AsyncMock(return_value={"ok": True, "ts": "TS"})
    monkeypatch.setattr(ws, "_get_effective_slack_features",
                        AsyncMock(return_value={"assistant_read": True, "assistant_write": True}))

    class FakeClient:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, json=None):
            return MagicMock()

    monkeypatch.setattr(ws.httpx, "AsyncClient", FakeClient)
    await ws._handle_block_action_inner({
        "actions": [{"action_id": "slot_1", "value": "{\"start\": \"s\", \"end\": \"e\"}", "text": "9am"}],
        "user": {"id": "U1", "team_id": "T-FROM-USER"}, "channel": "C-STR",
    })
    # team resolved from user.team_id; channel from a plain string.
    svc.get_bot_token_for_team.assert_awaited_with("T-FROM-USER")


# ---------------------------------------------------------------------------
# Route handlers invoked directly (counts the route-body branches in-process)
# ---------------------------------------------------------------------------

class _FakeRequest:
    def __init__(self, body: bytes, headers: dict, form: dict | None = None):
        self._body = body
        self.headers = headers
        self._form = form or {}

    async def body(self):
        return self._body

    async def form(self):
        return self._form


class _FakeBg:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))


@pytest.mark.asyncio
async def test_slack_events_handler_url_verification_direct():
    body = json.dumps({"type": "url_verification", "challenge": "ch-1"}).encode()
    req = _FakeRequest(body, {})
    bg = _FakeBg()
    out = await ws.slack_events(req, bg)
    assert out == {"challenge": "ch-1"}
    assert bg.tasks == []


@pytest.mark.asyncio
async def test_slack_events_handler_invalid_json_400_direct():
    from fastapi import HTTPException
    req = _FakeRequest(b"not-json", {})
    with pytest.raises(HTTPException) as exc:
        await ws.slack_events(req, _FakeBg())
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_slack_events_handler_bad_signature_401_direct(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(get_settings(), "SLACK_SIGNING_SECRET", SIGNING_SECRET, raising=False)
    body = json.dumps({"type": "event_callback", "event": {"type": "message"}}).encode()
    req = _FakeRequest(body, {"X-Slack-Request-Timestamp": str(int(time.time())), "X-Slack-Signature": "v0=bad"})
    with pytest.raises(HTTPException) as exc:
        await ws.slack_events(req, _FakeBg())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_slack_events_handler_im_dispatch_direct(monkeypatch):
    monkeypatch.setattr(get_settings(), "SLACK_SIGNING_SECRET", SIGNING_SECRET, raising=False)
    body = json.dumps({
        "type": "event_callback", "team_id": "T1",
        "event": {"type": "message", "channel_type": "im", "user": "U1", "text": "hi"},
    }).encode()
    req = _FakeRequest(body, _sign(body))
    bg = _FakeBg()
    out = await ws.slack_events(req, bg)
    assert out == {"ok": True}
    assert bg.tasks[0][0] is ws.handle_message_event


@pytest.mark.asyncio
async def test_slack_interactions_handler_bad_signature_401_direct(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(get_settings(), "SLACK_SIGNING_SECRET", SIGNING_SECRET, raising=False)
    body = b"payload=%7B%7D"
    req = _FakeRequest(body, {"X-Slack-Request-Timestamp": str(int(time.time())), "X-Slack-Signature": "v0=bad"})
    with pytest.raises(HTTPException) as exc:
        await ws.slack_interactions(req, _FakeBg())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_slack_interactions_handler_block_action_dispatch_direct(monkeypatch):
    monkeypatch.setattr(get_settings(), "SLACK_SIGNING_SECRET", SIGNING_SECRET, raising=False)
    payload = json.dumps({"type": "block_actions", "actions": [{"action_id": "x"}]})
    body = f"payload={payload}".encode()
    req = _FakeRequest(body, _sign(body), form={"payload": payload})
    bg = _FakeBg()
    out = await ws.slack_interactions(req, bg)
    assert out == {"ok": True}
    assert bg.tasks[0][0] is ws.handle_block_action


@pytest.mark.asyncio
async def test_slack_interactions_handler_empty_payload_direct(monkeypatch):
    monkeypatch.setattr(get_settings(), "SLACK_SIGNING_SECRET", SIGNING_SECRET, raising=False)
    body = b"payload="
    req = _FakeRequest(body, _sign(body), form={"payload": ""})
    out = await ws.slack_interactions(req, _FakeBg())
    assert out == {"ok": True}


@pytest.mark.asyncio
async def test_slack_interactions_handler_bad_json_payload_direct(monkeypatch):
    monkeypatch.setattr(get_settings(), "SLACK_SIGNING_SECRET", SIGNING_SECRET, raising=False)
    body = b"payload=not-json"
    req = _FakeRequest(body, _sign(body), form={"payload": "not-json"})
    out = await ws.slack_interactions(req, _FakeBg())
    assert out == {"ok": True}
