"""Tests for the global PostgrestError / RpcError / catch-all error envelope
(BE-F2).

These verify that errors raised below the router layer surface as a static,
non-leaky JSON envelope with the correct HTTP status — not a raw traceback or
a leaked DB message. Test-only routes are registered on the shared app so we
exercise the real handlers wired in `app/main.py` via
`register_v2_error_handlers`.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.supabase import PostgrestError, RpcError

# Test-only routes that raise below-the-router exceptions. Registered once at
# import time; harmless on the real app (paths are namespaced + only hit here).
_TEST_PREFIX = "/__test_errors__"


@app.get(_TEST_PREFIX + "/postgrest-undefined-table")
async def _raise_postgrest_undefined_table():
    raise PostgrestError(
        message='relation "candidates" does not exist',
        code="42P01",
    )


@app.get(_TEST_PREFIX + "/postgrest-unique-violation")
async def _raise_postgrest_unique_violation():
    raise PostgrestError(
        message="duplicate key value violates unique constraint",
        code="23505",
    )


@app.get(_TEST_PREFIX + "/postgrest-no-code")
async def _raise_postgrest_no_code():
    raise PostgrestError(message="something went wrong", code=None)


@app.get(_TEST_PREFIX + "/rpc-raw")
async def _raise_rpc_raw():
    # A call site that raised RpcError without going through call_rpc.
    raise RpcError(message="P0002", code="P0002")


@app.get(_TEST_PREFIX + "/boom")
async def _raise_unhandled():
    raise RuntimeError("super secret internal failure detail")


@pytest.fixture
def client():
    # raise_server_exceptions=False so the catch-all Exception handler is
    # exercised instead of the TestClient re-raising into the test.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _assert_no_leak(body: dict, *secrets: str):
    """The serialized body must not contain a traceback frame or any of the
    given raw internal strings."""
    blob = str(body)
    assert "Traceback" not in blob
    assert "File \"" not in blob
    for secret in secrets:
        assert secret not in blob


def test_postgrest_undefined_table_maps_to_500_static_envelope(client):
    resp = client.get(_TEST_PREFIX + "/postgrest-undefined-table")
    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"]["error"] == "db_error"
    assert body["detail"]["code"] == "42P01"
    # The raw DB message must not leak to the client.
    _assert_no_leak(body, "candidates", "does not exist")
    # Request id is echoed so the client can correlate.
    assert resp.headers.get("X-Request-ID")


def test_postgrest_unique_violation_maps_to_409(client):
    resp = client.get(_TEST_PREFIX + "/postgrest-unique-violation")
    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"]["error"] == "db_error"
    assert body["detail"]["code"] == "23505"
    _assert_no_leak(body, "duplicate key value")


def test_postgrest_unknown_code_defaults_to_500(client):
    resp = client.get(_TEST_PREFIX + "/postgrest-no-code")
    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"]["error"] == "db_error"
    _assert_no_leak(body, "something went wrong")


def test_raw_rpc_error_is_caught_as_safety_net(client):
    # P0002 -> NotFound intent -> 404 (reuses core.rpc mapping).
    resp = client.get(_TEST_PREFIX + "/rpc-raw")
    assert resp.status_code == 404
    body = resp.json()
    # NotFoundError handler owns this once mapped, so the detail is the
    # domain message string, not a raw SQLSTATE/traceback.
    _assert_no_leak(body)


def test_unhandled_exception_returns_static_500_envelope(client):
    resp = client.get(_TEST_PREFIX + "/boom")
    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"]["error"] == "internal_error"
    assert body["detail"]["request_id"]
    # The internal failure message must never reach the client.
    _assert_no_leak(body, "super secret internal failure detail", "RuntimeError")


def test_http_exception_behaviour_is_not_shadowed(client):
    # A genuinely missing route must still 404 via FastAPI's own handling,
    # not get swallowed by the catch-all Exception handler.
    resp = client.get("/__no_such_route_at_all__")
    assert resp.status_code == 404
    body = resp.json()
    # FastAPI's default 404 shape: {"detail": "Not Found"} — NOT our envelope.
    assert body["detail"] == "Not Found"
