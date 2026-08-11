"""API behaviour, with the secret-leak guard as the centrepiece.

This service holds every credential in the deployment. The single worst bug it
could have is returning one to a browser, so that is asserted directly rather
than inferred from the write-only design.
"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SAMPLE_ENV = """\
# Database
SUPABASE_URL=https://example.supabase.co
SUPABASE_SECRET_KEY=super-secret-service-key
ANTHROPIC_API_KEY=sk-ant-super-secret
DEEPGRAM_API_KEY=
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(SAMPLE_ENV, encoding="utf-8")
    monkeypatch.setenv("SETUP_ENV_PATH", str(env))
    monkeypatch.setenv("SETUP_ENV_EXAMPLE_PATH", str(tmp_path / "nope"))
    monkeypatch.setenv("SETUP_STATE_PATH", str(tmp_path / "password.json"))

    import importlib

    import app.main as main

    importlib.reload(main)
    return TestClient(main.app), main, env


def _signed_in(client_tuple):
    client, main, env = client_tuple
    token = client.post("/api/password", json={"password": "a-good-password"}).json()["token"]
    return client, main, env, {"x-setup-token": token}


def test_healthz_needs_no_auth_and_leaks_nothing(client):
    c, _, _ = client
    resp = c.get("/healthz")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_config_requires_authentication(client):
    c, _, _ = client

    assert c.get("/api/config").status_code == 401


def test_a_secret_value_is_never_returned_to_the_browser(client):
    """The worst bug this service could have."""
    c, _, _, headers = _signed_in(client)

    body = c.get("/api/config", headers=headers).text

    assert "super-secret-service-key" not in body
    assert "sk-ant-super-secret" not in body


def test_a_secret_is_reported_as_set_without_its_value(client):
    c, _, _, headers = _signed_in(client)

    groups = {g["id"]: g for g in c.get("/api/config", headers=headers).json()["groups"]}
    by_name = {v["name"]: v for v in groups["database"]["variables"]}

    assert by_name["SUPABASE_SECRET_KEY"]["set"] is True
    assert by_name["SUPABASE_SECRET_KEY"]["value"] == ""
    assert by_name["SUPABASE_URL"]["value"] == "https://example.supabase.co"


def test_an_unset_secret_reports_set_false(client):
    c, _, _, headers = _signed_in(client)

    groups = {g["id"]: g for g in c.get("/api/config", headers=headers).json()["groups"]}
    voice = {v["name"]: v for v in groups["voice"]["variables"]}

    assert voice["DEEPGRAM_API_KEY"]["set"] is False


def test_plan_reports_the_restarts_without_writing_anything(client):
    c, _, env, headers = _signed_in(client)
    before = env.read_text()

    resp = c.post("/api/plan", json={"changes": {"DEEPGRAM_API_KEY": "new"}}, headers=headers)

    assert resp.status_code == 200
    assert "voice-agent" in resp.json()["restarts"]
    assert "ends any call in progress" in resp.json()["warning"]
    assert env.read_text() == before, "plan must not write"


def test_an_unknown_setting_is_refused_rather_than_written(client):
    """Fail closed: a typo must not append a variable nothing reads."""
    c, _, env, headers = _signed_in(client)
    before = env.read_text()

    resp = c.post("/api/apply", json={"changes": {"NOT_REAL": "x"}}, headers=headers)

    assert resp.status_code == 400
    assert env.read_text() == before


def test_applying_writes_the_value_and_preserves_comments(client, monkeypatch):
    c, main, env, headers = _signed_in(client)

    async def no_restart(service):
        return None

    async def ok(service, timeout=90.0):
        return True

    monkeypatch.setattr(main.docker, "restart", no_restart)
    monkeypatch.setattr(main.docker, "wait_until_ok", ok)

    resp = c.post(
        "/api/apply", json={"changes": {"DEEPGRAM_API_KEY": "dg-key"}}, headers=headers
    )

    assert resp.status_code == 200
    text = env.read_text()
    assert "DEEPGRAM_API_KEY=dg-key" in text
    assert "# Database" in text, "comments must survive a save"
    assert resp.json()["backup"], "a backup must be written before overwriting .env"


def test_a_failed_restart_is_reported_per_service_not_raised(client, monkeypatch):
    """Five restarts must not collapse into one opaque error — the user needs
    to know WHICH came back unhealthy."""
    c, main, _, headers = _signed_in(client)

    async def restart(service):
        return None

    async def never_ok(service, timeout=90.0):
        return False

    monkeypatch.setattr(main.docker, "restart", restart)
    monkeypatch.setattr(main.docker, "wait_until_ok", never_ok)

    resp = c.post(
        "/api/apply", json={"changes": {"DEEPGRAM_API_KEY": "x"}}, headers=headers
    )

    assert resp.status_code == 200
    results = resp.json()["restarts"]
    assert all(r["ok"] is False for r in results)
    assert any(r["service"] == "voice-agent" for r in results)


def test_the_password_cannot_be_set_twice_over_http(client):
    c, _, _ = client
    c.post("/api/password", json={"password": "first-password"})

    resp = c.post("/api/password", json={"password": "attacker-password"})

    assert resp.status_code == 400
