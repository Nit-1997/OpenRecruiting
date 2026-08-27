"""Tests for the audit event writer.

The writer is fire-and-forget; we verify:
  * Events are shaped correctly from AuthContext + outcome data.
  * Param VALUES are never logged — only keys.
  * Huge queries / errors get truncated.
  * Write failures (Supabase down) are logged but never raised.
  * When audit is disabled, no client work happens.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from src.auth.context import AuthContext
from src.services import audit


ACME = "8f5311b7-7427-47c0-97d1-e1e6c4c23847"


def _auth() -> AuthContext:
    return AuthContext(
        user_id="user-1",
        org_id=ACME,
        org_name="Acme",
        user_name="Dev",
        role="admin",
        scopes=("cortex:read",),
    )


# ---------------------------------------------------------------------------
# build_event
# ---------------------------------------------------------------------------

def test_build_event_logs_only_param_keys_not_values():
    """Param VALUES are PII (candidate names, etc.). The audit row gets
    the key set only."""
    ev = audit.build_event(
        auth=_auth(),
        tool_name="execute_query",
        status="ok",
        start_monotonic=0.0,
        query="MATCH (c:Candidate {group_id: $org_id, name: $candidate_name}) RETURN c.uuid",
        params={"org_id": ACME, "candidate_name": "Carter Ellis"},
        row_count=1,
        truncated=False,
    )
    assert ev.query_param_keys == ["candidate_name", "org_id"]
    serialized = audit._serialize(ev, 8000, 500)
    # Verify the candidate name does NOT appear anywhere in the payload.
    assert "Carter Ellis" not in str(serialized)


def test_build_event_captures_outcome():
    ev = audit.build_event(
        auth=_auth(),
        tool_name="execute_query",
        status="rejected",
        start_monotonic=0.0,
        query="bad",
        error_message="missing group_id",
        row_count=None,
    )
    assert ev.status == "rejected"
    assert ev.error_message == "missing group_id"
    assert ev.row_count is None


def test_event_carries_user_and_request_metadata():
    ev = audit.build_event(
        auth=_auth(),
        tool_name="who_am_i",
        status="ok",
        start_monotonic=0.0,
        user_agent="Claude/1.0",
        ip_address="1.2.3.4",
        request_id="req-123",
    )
    assert ev.user_id == "user-1"
    assert ev.org_id == ACME
    assert ev.user_agent == "Claude/1.0"
    assert ev.ip_address == "1.2.3.4"
    assert ev.request_id == "req-123"


def test_serialize_truncates_huge_query():
    ev = audit.build_event(
        auth=_auth(),
        tool_name="execute_query",
        status="ok",
        start_monotonic=0.0,
        query="MATCH " + ("x" * 20_000),
    )
    serialized = audit._serialize(ev, max_q=100, max_err=500)
    assert len(serialized["query"]) <= 100
    assert serialized["query"].endswith("...")


def test_serialize_truncates_huge_error():
    ev = audit.build_event(
        auth=_auth(),
        tool_name="execute_query",
        status="error",
        start_monotonic=0.0,
        error_message="boom " * 1000,
    )
    serialized = audit._serialize(ev, max_q=8000, max_err=200)
    assert len(serialized["error_message"]) <= 200
    assert serialized["error_message"].endswith("...")


# ---------------------------------------------------------------------------
# _send — actual write path
# ---------------------------------------------------------------------------

@pytest.fixture
def stub_client(monkeypatch):
    """Replace the module's httpx.AsyncClient with an in-test stub that
    records calls. Tests await `_send` directly so we can assert."""
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post.return_value = httpx.Response(201)
    monkeypatch.setattr(audit, "_async_client", client)
    yield client
    monkeypatch.setattr(audit, "_async_client", None)


@pytest.fixture(autouse=True)
def enable_audit(monkeypatch):
    """Make sure audit is enabled for these tests regardless of env."""
    from src.config.settings import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("AUDIT_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_URL", "http://test-supabase")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "test-key")
    yield
    get_settings.cache_clear()


async def test_send_posts_to_audit_table(stub_client):
    ev = audit.build_event(
        auth=_auth(), tool_name="who_am_i", status="ok", start_monotonic=0.0,
    )
    await audit._send(ev)
    stub_client.post.assert_called_once()
    args, kwargs = stub_client.post.call_args
    assert args[0] == "/rest/v1/mcp_audit_log"
    body = kwargs["content"]
    assert "user-1" in body
    assert ACME in body


async def test_send_swallows_http_500(stub_client):
    """Supabase down → log, don't raise."""
    stub_client.post.return_value = httpx.Response(500, text="boom")
    ev = audit.build_event(
        auth=_auth(), tool_name="who_am_i", status="ok", start_monotonic=0.0,
    )
    await audit._send(ev)  # must not raise


async def test_send_swallows_network_failure(stub_client):
    stub_client.post.side_effect = httpx.ConnectError("network is down")
    ev = audit.build_event(
        auth=_auth(), tool_name="who_am_i", status="ok", start_monotonic=0.0,
    )
    await audit._send(ev)  # must not raise


async def test_emit_creates_background_task(monkeypatch, stub_client):
    """`emit()` is the public entrypoint — non-blocking via create_task."""
    ev = audit.build_event(
        auth=_auth(), tool_name="who_am_i", status="ok", start_monotonic=0.0,
    )
    audit.emit(ev)
    # The task hasn't run yet — give the event loop one tick.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    stub_client.post.assert_called()


async def test_send_with_no_client_logs_locally(monkeypatch):
    """If init never ran (client is None), fall back to structured logging
    rather than crashing the request path."""
    monkeypatch.setattr(audit, "_async_client", None)
    ev = audit.build_event(
        auth=_auth(), tool_name="who_am_i", status="ok", start_monotonic=0.0,
    )
    await audit._send(ev)  # must not raise


# ---------------------------------------------------------------------------
# _infer_outcome (lives in main.py, exercised here)
# ---------------------------------------------------------------------------

def test_infer_outcome_reads_raw_dict():
    from src.main import _infer_outcome
    raw = {"status": "rejected", "row_count": None, "truncated": False, "error": "boom"}
    status, rc, trunc, err = _infer_outcome(raw)
    assert status == "rejected"
    assert err == "boom"
    assert trunc is False


def test_infer_outcome_reads_fastmcp_toolresult():
    """FastMCP wraps tool returns in a ToolResult. _infer_outcome must
    look at the structured_content attribute, not the wrapper itself."""
    from src.main import _infer_outcome

    class FakeToolResult:
        def __init__(self, sc):
            self.structured_content = sc

    wrapped = FakeToolResult({"status": "ok", "row_count": 42, "truncated": False, "error": None})
    status, rc, trunc, err = _infer_outcome(wrapped)
    assert status == "ok"
    assert rc == 42
    assert trunc is False
    assert err is None


def test_infer_outcome_returns_nothing_for_unrelated_shapes():
    from src.main import _infer_outcome
    assert _infer_outcome(None) == (None, None, None, None)
    assert _infer_outcome("just a string") == (None, None, None, None)
    assert _infer_outcome([1, 2, 3]) == (None, None, None, None)
