"""
Tests for POST /api/v2/intake/parse-intent.

Auth is overridden via the conftest `recruiter_client` fixture (overrides
`get_current_user`; `get_current_user_with_org` resolves from it).
The gateway client dependency is replaced with llm-core's FakeLLM via
`app.dependency_overrides`; the conftest `clear_caches` fixture clears them on
teardown.
"""
from __future__ import annotations

from llm_core.errors import LLMError

from app.main import app
from app.dependencies import get_llm_client

V2_ROOT = "/api/v2"


def test_parse_intent_returns_extracted_fields(recruiter_client, fake_llm):
    fake_llm.queue_tool_call(
        "emit_role_fields",
        {"intent": "create_role", "role_name": "Senior Backend Engineer", "exp_min": 7},
    )
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    resp = recruiter_client.post(
        f"{V2_ROOT}/intake/parse-intent",
        json={"text": "senior backend eng, 7 yrs"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["role_name"] == "Senior Backend Engineer"
    assert body["exp_min"] == 7
    assert body["exp_max"] is None
    assert body["location"] is None
    assert body["intent"] == "create_role"
    assert body["list_status"] is None


def test_parse_intent_returns_all_none_on_llm_failure(recruiter_client, fake_llm):
    fake_llm.queue_error(LLMError("LLM exploded", alias="parse-role-intent"))
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    resp = recruiter_client.post(
        f"{V2_ROOT}/intake/parse-intent",
        json={"text": "something something role"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["role_name"] is None
    assert body["exp_min"] is None
    assert body["exp_max"] is None
    assert body["location"] is None
    assert body["intent"] == "other"
    assert body["list_status"] is None


def test_parse_intent_returns_list_sessions_intent(recruiter_client, fake_llm):
    fake_llm.queue_tool_call(
        "emit_role_fields", {"intent": "list_sessions", "list_status": "pending"}
    )
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    resp = recruiter_client.post(
        f"{V2_ROOT}/intake/parse-intent",
        json={"text": "show me pending intakes"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "list_sessions"
    assert body["list_status"] == "pending"
    assert body["role_name"] is None


def test_parse_intent_rejects_empty_text(recruiter_client, fake_llm):
    """422 fires before the service runs, so the empty queue is never consumed."""
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    resp = recruiter_client.post(
        f"{V2_ROOT}/intake/parse-intent",
        json={"text": ""},
    )
    assert resp.status_code == 422
    assert fake_llm.calls == []


def test_parse_intent_requires_auth(unauthed_client):
    resp = unauthed_client.post(
        f"{V2_ROOT}/intake/parse-intent",
        json={"text": "senior backend eng"},
    )
    assert resp.status_code in (401, 403)
