"""BE-S4 / BE-T1: staff-gate audit for the whole admin surface.

Every route mounted under `/api/v2/admin/*` must enforce `require_staff`.
This test introspects the live FastAPI app, enumerates every admin route, and
asserts that a non-staff authenticated caller is rejected with 403 on each one.

It is deliberately data-driven off `app.routes` so a future admin endpoint that
forgets the staff gate fails here automatically — no per-endpoint maintenance.
"""
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_user, require_staff
from tests.conftest import RECRUITER_USER  # non-staff CurrentUser

ADMIN_PREFIX = "/api/v2/admin"

# A representative method to probe per route. We pick the first non-HEAD method.
_PROBE_ORDER = ["GET", "POST", "PUT", "PATCH", "DELETE"]

# Path params get a syntactically valid UUID so routing matches; the request
# must be rejected at the auth dependency BEFORE any handler/DB code runs.
_DUMMY_UUID = "00000000-0000-0000-0000-0000000000ff"


def _admin_routes():
    routes = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        if not path.startswith(ADMIN_PREFIX):
            continue
        probe_methods = [m for m in _PROBE_ORDER if m in methods]
        if not probe_methods:
            continue
        routes.append((path, probe_methods[0]))
    return sorted(set(routes))


def _concrete_path(path: str) -> str:
    # Replace every {param} segment with a dummy UUID. All admin path params in
    # this surface are UUIDs except blog slug; a UUID-shaped string still routes
    # for slug paths (it's just a string), so this is safe across the board.
    return re.sub(r"\{[^}]+\}", _DUMMY_UUID, path)


@pytest.fixture
def non_staff_client(respx_mock):
    # Override only get_current_user with a non-staff user; require_staff
    # runs for real and must raise 403. We intentionally DO NOT override
    # require_staff here (unlike the staff_client fixture).
    app.dependency_overrides[get_current_user] = lambda: RECRUITER_USER
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_admin_surface_is_non_empty():
    # Guard against the introspection silently matching nothing.
    routes = _admin_routes()
    assert len(routes) >= 40, f"expected the full admin surface, found {len(routes)}"


@pytest.mark.parametrize("path,method", _admin_routes())
def test_admin_route_rejects_non_staff(non_staff_client, path, method):
    url = _concrete_path(path)
    # Send an empty JSON body for write methods so body-validation never short
    # circuits before the auth dependency; FastAPI resolves dependencies before
    # body for security deps, but an empty dict is harmless either way.
    resp = non_staff_client.request(method, url, json={})
    assert resp.status_code == 403, (
        f"{method} {url} returned {resp.status_code}, expected 403 "
        f"(staff gate missing?): {resp.text}"
    )
    assert "Staff access required" in resp.text
