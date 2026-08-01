"""Tests for POST /api/v2/assistant/route.

Auth is overridden via the conftest `recruiter_client` / `unauthed_client`
fixtures. The Anthropic client dependency is patched via app.dependency_overrides.
"""
from __future__ import annotations

from app.main import app
from app.dependencies import get_anthropic_async_client

V2_ROOT = "/api/v2"


class _FakeBlock:
    type = "tool_use"
    name = "emit_route"

    def __init__(self, intent):
        self.input = {"intent": intent}


class _FakeMsg:
    def __init__(self, blocks):
        self.content = blocks


def _client_emitting(intent):
    class _Messages:
        async def create(self, **kw):
            return _FakeMsg([_FakeBlock(intent)])

    class _Client:
        messages = _Messages()

    return _Client()


def test_route_returns_browse_roles(recruiter_client):
    app.dependency_overrides[get_anthropic_async_client] = lambda: _client_emitting("browse_roles")
    resp = recruiter_client.post(f"{V2_ROOT}/assistant/route", json={"text": "show me my open roles"})
    assert resp.status_code == 200
    assert resp.json()["intent"] == "browse_roles"


def test_route_returns_intake_call(recruiter_client):
    app.dependency_overrides[get_anthropic_async_client] = lambda: _client_emitting("intake_call")
    resp = recruiter_client.post(f"{V2_ROOT}/assistant/route", json={"text": "create a new role"})
    assert resp.status_code == 200
    assert resp.json()["intent"] == "intake_call"


def test_route_fail_open_out_of_scope_on_llm_error(recruiter_client):
    class _BrokenMessages:
        async def create(self, **kw):
            raise RuntimeError("LLM exploded")

    class _BrokenClient:
        messages = _BrokenMessages()

    app.dependency_overrides[get_anthropic_async_client] = lambda: _BrokenClient()
    resp = recruiter_client.post(f"{V2_ROOT}/assistant/route", json={"text": "anything"})
    assert resp.status_code == 200
    assert resp.json()["intent"] == "out_of_scope"


def test_route_rejects_empty_text(recruiter_client):
    app.dependency_overrides[get_anthropic_async_client] = lambda: _client_emitting("out_of_scope")
    resp = recruiter_client.post(f"{V2_ROOT}/assistant/route", json={"text": ""})
    assert resp.status_code == 422


def test_route_requires_auth(unauthed_client):
    resp = unauthed_client.post(f"{V2_ROOT}/assistant/route", json={"text": "show roles"})
    assert resp.status_code in (401, 403)
