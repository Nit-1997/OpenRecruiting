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
    # Supabase moved into Get started when the page was reorganised around what
    # a first run needs; the secret contract is what this test is about.
    by_name = {v["name"]: v for v in groups["start"]["variables"]}

    assert by_name["SUPABASE_SECRET_KEY"]["set"] is True
    assert by_name["SUPABASE_SECRET_KEY"]["value"] == ""
    assert by_name["SUPABASE_URL"]["value"] == "https://example.supabase.co"


def test_an_unset_secret_reports_set_false(client):
    c, _, _, headers = _signed_in(client)

    groups = {g["id"]: g for g in c.get("/api/config", headers=headers).json()["groups"]}
    start = {v["name"]: v for v in groups["start"]["variables"]}

    assert start["DEEPGRAM_API_KEY"]["set"] is False


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

    # Stub the APPLIER, not docker.restart: applying a setting now RECREATES
    # services, because a restart reuses the environment baked in at container
    # create time and silently changes nothing.
    async def recreated(services):
        return {"ok": True, "detail": "recreated", "services": " ".join(services)}

    async def ok(service, timeout=90.0):
        return True

    monkeypatch.setattr(main.applier, "recreate", recreated)
    monkeypatch.setattr(main.docker, "wait_until_ok", ok)

    resp = c.post(
        "/api/apply", json={"changes": {"DEEPGRAM_API_KEY": "dg-key"}}, headers=headers
    )

    assert resp.status_code == 200
    text = env.read_text()
    assert "DEEPGRAM_API_KEY=dg-key" in text
    assert "# Database" in text, "comments must survive a save"
    assert resp.json()["backup"], "a backup must be written before overwriting .env"


def test_health_waits_run_concurrently_not_one_after_another(client, monkeypatch):
    """These ran in a loop, so the wait was the SUM of every service's timeout.

    A Supabase change touches 11 services at 90s each: 990 seconds of polling
    inside one HTTP request that has sent no bytes. First runs hit it every time,
    because the containers that are not configured yet are exactly the ones that
    never come up, so each burned its full timeout. Browsers and proxies drop an
    idle request long before that and the page said `NetworkError when attempting
    to fetch resource`, which reads like the save failed — it had not, .env is
    written before any of this.

    Asserts overlap rather than wall-clock duration, so it cannot go flaky on a
    loaded machine: if the waits are sequential, no two are ever in flight
    together and peak concurrency is 1.
    """
    import asyncio

    c, main, env, headers = _signed_in(client)
    in_flight = 0
    peak = 0

    async def recreated(services):
        return {"ok": True, "detail": "recreated", "services": " ".join(services)}

    async def slow_ok(service, timeout=90.0):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await asyncio.sleep(0.05)
            return True
        finally:
            in_flight -= 1

    monkeypatch.setattr(main.applier, "recreate", recreated)
    monkeypatch.setattr(main.docker, "wait_until_ok", slow_ok)

    # SUPABASE_URL fans out to every Supabase consumer plus the frontends.
    resp = c.post(
        "/api/apply", json={"changes": {"SUPABASE_URL": "https://new.supabase.co"}},
        headers=headers,
    )

    assert resp.status_code == 200
    services = resp.json()["restarts"]
    assert len(services) > 3, "expected a multi-service fan-out to test against"
    assert peak == len(services), (
        f"health waits are running {peak} at a time across {len(services)} services — "
        "sequential waits are what made an 11-service save take ~19 minutes"
    )
    assert all(s["ok"] for s in services)


def test_one_health_check_blowing_up_does_not_discard_the_other_results(client, monkeypatch):
    """Which services came back is the whole answer the user is waiting for, so a
    single unexpected failure must not take the rest of the report with it."""
    c, main, env, headers = _signed_in(client)

    async def recreated(services):
        return {"ok": True, "detail": "recreated", "services": " ".join(services)}

    async def explode(service, timeout=90.0):
        if service == "backend":
            raise RuntimeError("boom")
        return True

    monkeypatch.setattr(main.applier, "recreate", recreated)
    monkeypatch.setattr(main.docker, "wait_until_ok", explode)

    resp = c.post(
        "/api/apply", json={"changes": {"SUPABASE_URL": "https://new.supabase.co"}},
        headers=headers,
    )

    assert resp.status_code == 200
    by_name = {s["service"]: s for s in resp.json()["restarts"]}
    assert by_name["backend"]["ok"] is False
    assert "boom" in by_name["backend"]["detail"]
    assert by_name["landing"]["ok"] is True, "an unrelated service must still report"


def test_a_failed_restart_is_reported_per_service_not_raised(client, monkeypatch):
    """Five restarts must not collapse into one opaque error — the user needs
    to know WHICH came back unhealthy."""
    c, main, _, headers = _signed_in(client)

    async def recreated(services):
        return {"ok": True, "detail": "recreated", "services": " ".join(services)}

    async def never_ok(service, timeout=90.0):
        return False

    monkeypatch.setattr(main.applier, "recreate", recreated)
    monkeypatch.setattr(main.docker, "wait_until_ok", never_ok)

    resp = c.post(
        "/api/apply", json={"changes": {"DEEPGRAM_API_KEY": "x"}}, headers=headers
    )

    assert resp.status_code == 200
    results = resp.json()["restarts"]
    assert all(r["ok"] is False for r in results)
    assert any(r["service"] == "voice-agent" for r in results)
    assert any("not healthy" in r["detail"] for r in results)


def test_the_password_cannot_be_set_twice_over_http(client):
    c, _, _ = client
    c.post("/api/password", json={"password": "first-password"})

    resp = c.post("/api/password", json={"password": "attacker-password"})

    assert resp.status_code == 400


def test_a_save_never_silently_skips_the_recreate(client, monkeypatch):
    """The original defect, pinned. If applying cannot run, the response must
    say so per service — a save that reports success while nothing was applied
    is the exact bug this replaced."""
    c, main, env, headers = _signed_in(client)

    from app.applier import ApplyError

    async def unavailable(services):
        raise ApplyError("the applier state directory is not mounted")

    monkeypatch.setattr(main.applier, "recreate", unavailable)

    resp = c.post("/api/apply", json={"changes": {"DEEPGRAM_API_KEY": "x"}}, headers=headers)

    assert resp.status_code == 200
    results = resp.json()["restarts"]
    assert results, "affected services must still be reported"
    assert all(r["ok"] is False for r in results)
    assert all("not mounted" in r["detail"] for r in results)
    # The value is still written — the user should not have to retype it.
    assert "DEEPGRAM_API_KEY=x" in env.read_text()


# ── the composite public-address field ──────────────────────────────────────
# It is not a real variable, so these check the seam: it must be expanded before
# validation (or it is rejected as unknown) and before restart scoping (or the
# containers that read the eight real values never bounce).


def test_public_address_is_offered_as_one_field_in_get_started(client):
    c, _, _, headers = _signed_in(client)
    groups = {g["id"]: g for g in c.get("/api/config", headers=headers).json()["groups"]}

    start = groups["start"]
    assert start["tier"] == "start"
    names = [v["name"] for v in start["variables"]]
    assert names[0] == "PUBLIC_BASE_URL", "the composite leads Get started"
    # The eight it writes must not ALSO be editable here.
    assert not {"OIDC_ISSUER", "WEBHOOK_BASE_URL"} & set(names)


def test_derived_values_are_returned_readonly(client):
    c, _, _, headers = _signed_in(client)
    groups = {g["id"]: g for g in c.get("/api/config", headers=headers).json()["groups"]}

    assert groups["derived"]["tier"] == "internal"
    assert all(v["readonly"] for v in groups["derived"]["variables"])
    assert all(not v["readonly"] for v in groups["start"]["variables"])


def test_plan_expands_the_composite_instead_of_rejecting_it(client):
    """Unexpanded, PUBLIC_BASE_URL is not in all_variables() and /api/plan would
    400 it as an unknown setting."""
    c, _, env, headers = _signed_in(client)
    before = env.read_text()

    body = c.post(
        "/api/plan", json={"changes": {"PUBLIC_BASE_URL": "or.example.ai"}}, headers=headers
    ).json()

    assert "PUBLIC_BASE_URL" not in body["changes"]
    assert "OIDC_ISSUER" in body["changes"]
    assert "MCP_ALLOWED_AUDIENCES" in body["changes"]
    # Restarts are scoped from the REAL variables, so cortex-mcp is included —
    # it reads the issuer and the audience list.
    assert "cortex-mcp" in body["restarts"]
    assert "backend" in body["restarts"]
    assert env.read_text() == before, "plan must not write"


def test_applying_the_composite_writes_every_derived_value(client, monkeypatch):
    c, main, env, headers = _signed_in(client)

    async def recreated(services):
        return {"ok": True, "detail": "recreated", "services": " ".join(services)}

    async def ok(service, timeout=90.0):
        return True

    monkeypatch.setattr(main.applier, "recreate", recreated)
    monkeypatch.setattr(main.docker, "wait_until_ok", ok)

    resp = c.post(
        "/api/apply", json={"changes": {"PUBLIC_BASE_URL": "or.example.ai"}}, headers=headers
    )

    assert resp.status_code == 200
    text = env.read_text()
    host = "https://or.example.ai"
    assert f"WEBHOOK_BASE_URL={host}" in text
    assert f"VOICE_AGENT_URL={host}" in text
    assert f"CORTEX_PUBLIC_URL={host}" in text
    assert f"MCP_JWT_ISSUER={host}" in text
    assert f"OIDC_ISSUER={host}" in text
    assert f"MCP_ALLOWED_AUDIENCES=cortex-mcp,{host}" in text
    assert f"OIDC_AUDIENCE=cortex-mcp,{host}" in text
    assert f"NEXT_PUBLIC_CORTEX_MCP_URL={host}/mcp" in text
    # PUBLIC_BASE_URL itself is a UI concept and must never land in .env.
    assert "PUBLIC_BASE_URL" not in text
    # The report names what was actually written, not the field that was typed.
    assert "OIDC_ISSUER" in resp.json()["saved"]


def test_a_supabase_key_writes_both_of_its_names(client, monkeypatch):
    """`.env` says "set BOTH to the same value" — the UI does it now."""
    c, main, env, headers = _signed_in(client)

    async def recreated(services):
        return {"ok": True, "detail": "recreated", "services": " ".join(services)}

    async def ok(service, timeout=90.0):
        return True

    monkeypatch.setattr(main.applier, "recreate", recreated)
    monkeypatch.setattr(main.docker, "wait_until_ok", ok)

    c.post(
        "/api/apply",
        json={"changes": {"NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY": "sb_pub_x"}},
        headers=headers,
    )
    text = env.read_text()
    assert "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_pub_x" in text
    assert "NEXT_PUBLIC_SUPABASE_ANON_KEY=sb_pub_x" in text


# ── readiness ───────────────────────────────────────────────────────────────

def test_readiness_requires_authentication(client):
    c, _, _ = client

    assert c.get("/api/readiness").status_code == 401


def test_readiness_reports_every_feature_with_its_consequence(client):
    c, _, _, headers = _signed_in(client)

    body = c.get("/api/readiness", headers=headers).json()

    assert body["features"]
    for feature in body["features"]:
        assert set(feature) == {"id", "name", "state", "missing", "consequence", "required", "doc"}
        assert feature["state"] in {"live", "partial", "dormant", "unknown"}
        assert feature["consequence"]


def test_readiness_reflects_the_env_file_it_reads(client):
    """Written straight from .env, so a saved value shows up on the next read."""
    c, main, env, headers = _signed_in(client)

    before = {f["id"]: f for f in c.get("/api/readiness", headers=headers).json()["features"]}
    assert before["ats"]["state"] == "dormant"

    env.write_text(env.read_text(encoding="utf-8") + "\nKNIT_API_KEY=abc123\n", encoding="utf-8")

    after = {f["id"]: f for f in c.get("/api/readiness", headers=headers).json()["features"]}
    assert after["ats"]["state"] == "live"


def test_readiness_marks_required_features_so_the_panel_can_rank_them(client):
    """An unset required feature must be distinguishable from one that is off by
    choice; the panel renders the two differently."""
    c, _, _, headers = _signed_in(client)

    features = {f["id"]: f for f in c.get("/api/readiness", headers=headers).json()["features"]}

    assert features["core"]["required"] is True
    assert features["email"]["required"] is True
    assert features["ats"]["required"] is False
    assert features["google_auth"]["required"] is False


def test_readiness_never_claims_google_auth_works(client):
    c, _, _, headers = _signed_in(client)

    features = {f["id"]: f for f in c.get("/api/readiness", headers=headers).json()["features"]}

    assert features["google_auth"]["state"] == "unknown"
    assert features["google_auth"]["doc"]
