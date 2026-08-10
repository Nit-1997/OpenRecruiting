"""Tests for POST /api/v2/assistant/route.

Auth is overridden via the conftest `recruiter_client` / `unauthed_client`
fixtures. The gateway client dependency is replaced with llm-core's FakeLLM via
app.dependency_overrides.
"""
from __future__ import annotations

from llm_core.errors import LLMError

from app.dependencies import get_llm_client
from app.main import app

V2_ROOT = "/api/v2"


def test_route_returns_browse_roles(recruiter_client, fake_llm):
    fake_llm.queue_tool_call("emit_route", {"intent": "browse_roles"})
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    resp = recruiter_client.post(f"{V2_ROOT}/assistant/route", json={"text": "show me my open roles"})
    assert resp.status_code == 200
    assert resp.json()["intent"] == "browse_roles"


def test_route_returns_intake_call(recruiter_client, fake_llm):
    fake_llm.queue_tool_call("emit_route", {"intent": "intake_call"})
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    resp = recruiter_client.post(f"{V2_ROOT}/assistant/route", json={"text": "create a new role"})
    assert resp.status_code == 200
    assert resp.json()["intent"] == "intake_call"


def test_route_fail_open_out_of_scope_on_llm_error(recruiter_client, fake_llm):
    fake_llm.queue_error(LLMError("LLM exploded", alias="route-intent"))
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    resp = recruiter_client.post(f"{V2_ROOT}/assistant/route", json={"text": "anything"})
    assert resp.status_code == 200
    assert resp.json()["intent"] == "out_of_scope"


def test_route_rejects_empty_text(recruiter_client, fake_llm):
    """422 fires before the service runs, so nothing is consumed."""
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    resp = recruiter_client.post(f"{V2_ROOT}/assistant/route", json={"text": ""})
    assert resp.status_code == 422
    assert fake_llm.calls == []


def test_route_requires_auth(unauthed_client):
    resp = unauthed_client.post(f"{V2_ROOT}/assistant/route", json={"text": "show roles"})
    assert resp.status_code in (401, 403)
