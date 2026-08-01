"""Integration test for PATCH /api/v2/intake/sessions/{id}/answers."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.main import app


SESSION_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client():
    return TestClient(app)


def _override_auth(monkeypatch, user_id="22222222-2222-2222-2222-222222222222", org_id="33333333-3333-3333-3333-333333333333"):
    from app.api.v2.core.dependencies import get_current_user_with_org, CurrentUserWithOrg
    fake_user = MagicMock(id=UUID(user_id))
    fake_current = CurrentUserWithOrg(user=fake_user, organization_id=UUID(org_id))
    app.dependency_overrides[get_current_user_with_org] = lambda: fake_current


def _override_supabase(monkeypatch, sb_mock):
    from app.api.v2.core.dependencies import get_supabase
    app.dependency_overrides[get_supabase] = lambda: sb_mock


def test_patch_returns_200_and_applied_qids(monkeypatch, client):
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.single.return_value.execute_async = AsyncMock(
        return_value=MagicMock(
            data={"id": SESSION_ID, "user_id": "22222222-2222-2222-2222-222222222222", "organization_id": "33333333-3333-3333-3333-333333333333"}
        )
    )
    _override_auth(monkeypatch)
    _override_supabase(monkeypatch, sb)
    with patch("app.services.intake_manual_edit_service.aupdate_current_answers", new=AsyncMock()):
        resp = client.patch(
            f"/api/v2/intake/sessions/{SESSION_ID}/answers",
            json={"patch": {"q4_must_haves": {"text": "Python", "status": "validated"}}},
        )
    assert resp.status_code == 200
    assert resp.json() == {"applied": ["q4_must_haves"]}
    app.dependency_overrides.clear()


def test_patch_returns_404_when_session_missing(monkeypatch, client):
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.single.return_value.execute_async = AsyncMock(
        return_value=MagicMock(data=None)
    )
    _override_auth(monkeypatch)
    _override_supabase(monkeypatch, sb)
    resp = client.patch(
        f"/api/v2/intake/sessions/{SESSION_ID}/answers",
        json={"patch": {"q4_must_haves": {"text": "Python"}}},
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()
    app.dependency_overrides.clear()


def test_patch_returns_422_on_unknown_qid(monkeypatch, client):
    _override_auth(monkeypatch)
    _override_supabase(monkeypatch, MagicMock())
    resp = client.patch(
        f"/api/v2/intake/sessions/{SESSION_ID}/answers",
        json={"patch": {"q99_unknown": {"text": "x"}}},
    )
    assert resp.status_code == 422
    app.dependency_overrides.clear()


def test_patch_returns_422_on_invalid_status(monkeypatch, client):
    _override_auth(monkeypatch)
    _override_supabase(monkeypatch, MagicMock())
    resp = client.patch(
        f"/api/v2/intake/sessions/{SESSION_ID}/answers",
        json={"patch": {"q1_role_overview": {"status": "kinda_done"}}},
    )
    assert resp.status_code == 422
    app.dependency_overrides.clear()


def test_patch_returns_422_on_empty_patch(monkeypatch, client):
    _override_auth(monkeypatch)
    _override_supabase(monkeypatch, MagicMock())
    resp = client.patch(
        f"/api/v2/intake/sessions/{SESSION_ID}/answers",
        json={"patch": {}},
    )
    assert resp.status_code == 422
    app.dependency_overrides.clear()
