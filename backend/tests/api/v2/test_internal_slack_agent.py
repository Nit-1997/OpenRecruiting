"""Tests for the internal slack-agent endpoints' secret guard + invite path.

These endpoints adopt the shared `verify_internal_secret` dependency
(`app/api/v2/core/dependencies.py`), which returns 401 (not the legacy inline
403) on a bad/missing secret. Internal-only endpoints — clients should not
branch on 401-vs-403 for a bad secret, so the status was standardised to 401.
"""

INTERNAL_SECRET = "test-internal-secret"


def test_create_requisition_rejects_wrong_internal_secret(unauthed_client):
    resp = unauthed_client.post(
        "/api/v2/internal/requisitions",
        headers={"X-Internal-Secret": "wrong-secret"},
        json={"org_id": "o1", "profile_id": "p1", "role_title": "Engineer"},
    )
    assert resp.status_code == 401


def test_create_requisition_rejects_missing_internal_secret(unauthed_client):
    # No X-Internal-Secret header at all -> required-header 422, never reaches handler.
    resp = unauthed_client.post(
        "/api/v2/internal/requisitions",
        json={"org_id": "o1", "profile_id": "p1", "role_title": "Engineer"},
    )
    assert resp.status_code in (401, 422)


def test_internal_routes_are_mounted(unauthed_client):
    # Reaching the secret guard (401) or body validation (422) proves the
    # route exists and is mounted; a wrong secret never reaches the handler.
    for path in ["/api/v2/internal/candidates", "/api/v2/internal/team/invite"]:
        resp = unauthed_client.post(path, headers={"X-Internal-Secret": "wrong"}, json={})
        assert resp.status_code in (401, 422), f"{path} -> {resp.status_code}"


def test_no_inline_internal_secret_check_in_slack_agent_router():
    """The copy-pasted inline `verify_internal_secret` must be gone; the router
    adopts the shared dependency instead."""
    import inspect

    from app.api.v2.routers import internal_slack_agent

    src = inspect.getsource(internal_slack_agent)
    assert "def verify_internal_secret" not in src
    assert "status_code=403" not in src
