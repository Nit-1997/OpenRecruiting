"""
Tests for POST /api/v2/intake/parse-intent.

Auth is overridden via the conftest `recruiter_client` fixture (overrides
`get_current_user`; `get_current_user_with_org` resolves from it).
The Anthropic client dependency is patched via `app.dependency_overrides`.
"""
from __future__ import annotations

import pytest

from app.main import app
from app.dependencies import get_anthropic_async_client

V2_ROOT = "/api/v2"


class _FakeBlock:
    type = "tool_use"
    name = "emit_role_fields"

    def __init__(self, input_data: dict) -> None:
        self.input = input_data


class _FakeMsg:
    def __init__(self, blocks: list) -> None:
        self.content = blocks


class _FakeMessages:
    async def create(self, **kw):
        return _FakeMsg([_FakeBlock({"intent": "create_role", "role_name": "Senior Backend Engineer", "exp_min": 7})])


class _FakeClient:
    messages = _FakeMessages()


def test_parse_intent_returns_extracted_fields(recruiter_client):
    app.dependency_overrides[get_anthropic_async_client] = lambda: _FakeClient()
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


def test_parse_intent_returns_all_none_on_llm_failure(recruiter_client):
    class _BrokenMessages:
        async def create(self, **kw):
            raise RuntimeError("LLM exploded")

    class _BrokenClient:
        messages = _BrokenMessages()

    app.dependency_overrides[get_anthropic_async_client] = lambda: _BrokenClient()
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


def test_parse_intent_returns_list_sessions_intent(recruiter_client):
    class _ListMessages:
        async def create(self, **kw):
            return _FakeMsg([_FakeBlock({"intent": "list_sessions", "list_status": "pending"})])

    class _ListClient:
        messages = _ListMessages()

    app.dependency_overrides[get_anthropic_async_client] = lambda: _ListClient()
    resp = recruiter_client.post(
        f"{V2_ROOT}/intake/parse-intent",
        json={"text": "show me pending intakes"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "list_sessions"
    assert body["list_status"] == "pending"
    assert body["role_name"] is None


def test_parse_intent_rejects_empty_text(recruiter_client):
    app.dependency_overrides[get_anthropic_async_client] = lambda: _FakeClient()
    resp = recruiter_client.post(
        f"{V2_ROOT}/intake/parse-intent",
        json={"text": ""},
    )
    assert resp.status_code == 422


def test_parse_intent_requires_auth(unauthed_client):
    resp = unauthed_client.post(
        f"{V2_ROOT}/intake/parse-intent",
        json={"text": "senior backend eng"},
    )
    assert resp.status_code in (401, 403)
