"""The provider endpoints, and the leak guard applied to the new key field.

Adding a provider means writing a credential, so the assertion that matters most
here is the same one test_api.py leads with: a key goes in and never comes back.
An OpenRouter key is exactly the kind of value someone pastes into a browser
form and would never expect to be echoed into a JSON response.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

SAMPLE_ENV = """\
SUPABASE_URL=https://example.supabase.co
ANTHROPIC_API_KEY=sk-ant-super-secret
OPENROUTER_API_KEY=
LITELLM_MASTER_KEY=sk-gateway-master
LLM_GATEWAY_URL=http://litellm:4000
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(SAMPLE_ENV, encoding="utf-8")
    registry = tmp_path / "llm-providers.json"
    config = tmp_path / "litellm-config.yaml"

    monkeypatch.setenv("SETUP_ENV_PATH", str(env))
    monkeypatch.setenv("SETUP_ENV_EXAMPLE_PATH", str(tmp_path / "nope"))
    monkeypatch.setenv("SETUP_STATE_PATH", str(tmp_path / "password.json"))
    monkeypatch.setenv("SETUP_REGISTRY_PATH", str(registry))
    monkeypatch.setenv("SETUP_LITELLM_PATH", str(config))

    import importlib

    import app.catalogue as catalogue
    import app.main as main

    importlib.reload(main)
    catalogue.reset()

    # No Docker, no sidecar and no network in a unit test. All three are
    # exercised for real by the live suite; here they would only make the tests
    # slow and flaky. The applier in particular polls for a result file for a
    # full 180 seconds when no sidecar answers, which hangs the run rather than
    # failing it — stub it or every key-bearing save costs three minutes.
    async def _restart(_service):
        return None

    async def _wait(_service, timeout=90.0):
        return True

    async def _fetch(_provider_id):
        return {}

    async def _recreate(services):
        return {"ok": True, "detail": "recreated", "services": " ".join(services)}

    monkeypatch.setattr(main.docker, "restart", _restart)
    monkeypatch.setattr(main.docker, "wait_until_ok", _wait)
    monkeypatch.setattr(main.catalogue, "fetch", _fetch)
    monkeypatch.setattr(main.applier, "recreate", _recreate)

    c = TestClient(main.app)
    token = c.post("/api/password", json={"password": "a-good-password"}).json()["token"]
    return c, {"x-setup-token": token}, env, registry, config


def test_providers_require_authentication(client):
    c, _, _, _, _ = client
    assert c.get("/api/providers").status_code == 401
    assert c.post("/api/providers", json={"provider": "openai", "preferred": "x"}).status_code == 401


def test_a_fresh_install_reports_the_built_in_defaults(client):
    """No registry file yet. It must not read as "nothing configured" — that is
    what a fresh clone actually runs."""
    c, auth, _, _, _ = client
    body = c.get("/api/providers", headers=auth).json()

    assert body["default"] == "anthropic"
    assert {p["id"] for p in body["configured"]} == {"anthropic", "openai", "ollama"}
    assert {p["id"] for p in body["available"]} == {
        "anthropic",
        "openai",
        "openrouter",
        "ollama",
    }


def test_adding_a_provider_writes_its_key_to_env_and_never_returns_it(client):
    c, auth, env, _, _ = client
    secret = "sk-or-v1-this-must-never-come-back"

    resp = c.post(
        "/api/providers",
        headers=auth,
        json={
            "provider": "openrouter",
            "preferred": "deepseek/deepseek-v4-flash",
            "api_key": secret,
        },
    )

    assert resp.status_code == 200
    assert secret not in resp.text, "the API returned a credential to the browser"
    assert f"OPENROUTER_API_KEY={secret}" in env.read_text(encoding="utf-8")


def test_the_key_is_reported_as_set_but_never_by_value(client):
    c, auth, _, _, _ = client
    c.post(
        "/api/providers",
        headers=auth,
        json={"provider": "openrouter", "preferred": "x/y", "api_key": "sk-or-v1-secret"},
    )

    body = c.get("/api/providers", headers=auth)
    entry = next(p for p in body.json()["configured"] if p["id"] == "openrouter")
    assert entry["key_set"] is True
    assert "sk-or-v1-secret" not in body.text


def test_a_provider_configured_without_a_key_reports_key_set_false(client):
    """The failure this feature exists to prevent: a provider that looks
    configured while its credential is empty."""
    c, auth, _, _, _ = client
    c.post("/api/providers", headers=auth, json={"provider": "openrouter", "preferred": "x/y"})

    entry = next(
        p for p in c.get("/api/providers", headers=auth).json()["configured"]
        if p["id"] == "openrouter"
    )
    assert entry["key_set"] is False


def test_adding_a_provider_regenerates_the_gateway_config(client):
    c, auth, _, registry, config = client
    c.post(
        "/api/providers",
        headers=auth,
        json={
            "provider": "openrouter",
            "preferred": "z-ai/glm-5.2",
            "fast": "deepseek/deepseek-v4-flash",
            "make_default": True,
        },
    )

    assert json.loads(registry.read_text())["default"] == "openrouter"
    entries = {
        m["model_name"]: m for m in yaml.safe_load(config.read_text())["model_list"]
    }
    assert entries["debrief-chat"]["litellm_params"]["model"] == "openrouter/z-ai/glm-5.2"
    assert (
        entries["intake-jd"]["litellm_params"]["model"]
        == "openrouter/deepseek/deepseek-v4-flash"
    ), "the cheap tier must follow the fast slot"


def test_the_first_provider_added_becomes_the_default(client):
    """'I want the first one to be selected as default.'"""
    c, auth, _, registry, _ = client
    # Start from a registry with exactly one provider, as a real first run would.
    registry.write_text(json.dumps({"default": "openai", "providers": {"openai": {"preferred": "gpt-5.6-terra"}}}))
    c.delete("/api/providers/openai", headers=auth)  # only provider: refused
    c.post("/api/providers", headers=auth, json={"provider": "anthropic", "preferred": "claude-sonnet-5"})

    assert json.loads(registry.read_text())["default"] == "openai"


def test_the_last_provider_cannot_be_removed(client):
    c, auth, _, registry, _ = client
    registry.write_text(
        json.dumps({"default": "openai", "providers": {"openai": {"preferred": "gpt-5.6-terra"}}})
    )

    resp = c.delete("/api/providers/openai", headers=auth)
    assert resp.status_code == 400
    assert "only provider" in resp.json()["detail"]


def test_removing_a_provider_drops_the_overrides_that_pointed_at_it(client):
    """An override naming a provider that no longer exists makes the config
    unrenderable, which would lock the user out of the page that fixes it."""
    c, auth, _, registry, _ = client
    registry.write_text(
        json.dumps(
            {
                "default": "anthropic",
                "providers": {
                    "anthropic": {"preferred": "claude-sonnet-5"},
                    "openai": {"preferred": "gpt-5.6-terra"},
                },
                "overrides": {"screening-assessor": {"provider": "openai", "model": "gpt-5.6-terra"}},
            }
        )
    )

    resp = c.delete("/api/providers/openai", headers=auth)

    assert resp.status_code == 200
    assert resp.json()["dropped_overrides"] == ["screening-assessor"]
    assert json.loads(registry.read_text())["overrides"] == {}


def test_removing_the_default_provider_promotes_another(client):
    c, auth, _, registry, _ = client
    resp = c.delete("/api/providers/anthropic", headers=auth)

    assert resp.status_code == 200
    assert resp.json()["default"] in {"openai", "ollama"}
    assert json.loads(registry.read_text())["default"] == resp.json()["default"]


def test_an_unknown_provider_is_refused(client):
    c, auth, _, _, _ = client
    resp = c.post("/api/providers", headers=auth, json={"provider": "hal9000", "preferred": "x"})

    assert resp.status_code == 400
    assert "hal9000" in resp.json()["detail"]


def test_a_provider_without_a_model_is_refused(client):
    c, auth, _, _, _ = client
    resp = c.post("/api/providers", headers=auth, json={"provider": "openai", "preferred": "  "})

    assert resp.status_code == 400


# ── per-workload overrides ──────────────────────────────────────────────────


def test_models_lists_every_workload_with_what_it_resolves_to(client):
    c, auth, _, _, _ = client
    # /api/models reads the generated file, so generate one first.
    c.post("/api/providers", headers=auth, json={"provider": "anthropic", "preferred": "claude-sonnet-5"})

    body = c.get("/api/models", headers=auth).json()
    names = {a["name"] for a in body["aliases"]}

    assert "screening-assessor" in names
    assert "intake-jd" in names
    tiers = {a["name"]: a["tier"] for a in body["aliases"]}
    assert tiers["intake-jd"] == "fast"
    assert tiers["screening-assessor"] == "standard"


def test_an_override_repoints_one_workload_and_leaves_its_neighbours(client):
    c, auth, _, registry, config = client
    resp = c.post(
        "/api/models",
        headers=auth,
        json={"alias": "screening-assessor", "provider": "openai", "model": "gpt-5.6-terra"},
    )

    assert resp.status_code == 200
    entries = {m["model_name"]: m for m in yaml.safe_load(config.read_text())["model_list"]}
    assert entries["screening-assessor"]["litellm_params"]["model"] == "openai/gpt-5.6-terra"
    assert entries["screening-generator"]["litellm_params"]["model"] == "anthropic/claude-sonnet-5"


def test_clearing_an_override_returns_the_workload_to_the_default(client):
    c, auth, _, registry, config = client
    c.post(
        "/api/models",
        headers=auth,
        json={"alias": "screening-assessor", "provider": "openai", "model": "gpt-5.6-terra"},
    )
    resp = c.post("/api/models", headers=auth, json={"alias": "screening-assessor"})

    assert resp.status_code == 200
    assert resp.json()["override"] is None
    entries = {m["model_name"]: m for m in yaml.safe_load(config.read_text())["model_list"]}
    assert entries["screening-assessor"]["litellm_params"]["model"] == "anthropic/claude-sonnet-5"


def test_an_override_naming_an_unconfigured_provider_is_refused(client):
    c, auth, _, _, _ = client
    resp = c.post(
        "/api/models",
        headers=auth,
        json={"alias": "screening-assessor", "provider": "openrouter", "model": "x/y"},
    )

    assert resp.status_code == 400
    assert "not configured" in resp.json()["detail"]


def test_an_override_for_an_unknown_workload_is_refused(client):
    c, auth, _, _, _ = client
    resp = c.post(
        "/api/models",
        headers=auth,
        json={"alias": "not-a-workload", "provider": "anthropic", "model": "claude-sonnet-5"},
    )

    assert resp.status_code == 400


# ── probe ───────────────────────────────────────────────────────────────────


def test_probing_a_provider_with_no_key_is_refused_before_spending_anything(client):
    c, auth, _, _, _ = client
    resp = c.post(
        "/api/probe", headers=auth, json={"provider": "openrouter", "model": "z-ai/glm-5.2"}
    )

    assert resp.status_code == 400
    assert "OPENROUTER_API_KEY" in resp.json()["detail"]


def test_probing_requires_authentication(client):
    c, _, _, _, _ = client
    assert c.post("/api/probe", json={"provider": "anthropic", "model": "x"}).status_code == 401


def test_probing_an_unconfigured_provider_explains_what_to_do(client):
    """The gateway's wildcard route only exists for saved providers, so this
    otherwise fails deep inside litellm as "no healthy deployments" — which tells
    the user nothing about pressing Add +."""
    c, auth, env, registry, _ = client
    env.write_text(SAMPLE_ENV.replace("OPENROUTER_API_KEY=", "OPENROUTER_API_KEY=sk-or-v1-x"))
    registry.write_text(
        json.dumps({"default": "anthropic", "providers": {"anthropic": {"preferred": "claude-sonnet-5"}}})
    )

    resp = c.post("/api/probe", headers=auth, json={"provider": "openrouter", "model": "z-ai/glm-5.2"})

    assert resp.status_code == 400
    assert "Add OpenRouter first" in resp.json()["detail"]


def test_the_probe_runs_with_the_same_quirks_the_generator_would_write(client, monkeypatch):
    """The wildcard route carries no per-model settings. Probing without them
    measured a configuration nobody runs: it failed z-ai/glm-5.2 on an empty
    reply and a silent stream, both of which are what its reasoning quirk fixes.
    A probe that condemns a model the product would have used correctly is worse
    than no probe."""
    import app.main as main
    from app.probe import Check, ProbeResult

    seen: dict = {}

    async def _fetch(provider_id):
        if provider_id != "openrouter":
            return {}
        return {
            "openrouter/z-ai/glm-5.2": {
                "supported_parameters": ["tools"],
                "reasoning": {"default_enabled": True, "supported_efforts": ["xhigh", "high"]},
            }
        }

    async def _run(self, prefix, provider_id, model_id, quirk_params=None, quirk_notes=()):
        seen["params"] = quirk_params
        seen["notes"] = quirk_notes
        return ProbeResult(
            model=model_id, provider=provider_id,
            checks=[Check("Returns text", True, "'ready'")], ok=True,
            applied=quirk_notes,
        )

    monkeypatch.setattr(main.catalogue, "fetch", _fetch)
    monkeypatch.setattr(main.Prober, "run", _run)

    c, auth, env, _, _ = client
    env.write_text(SAMPLE_ENV.replace("OPENROUTER_API_KEY=", "OPENROUTER_API_KEY=sk-or-v1-x"))
    c.post("/api/providers", headers=auth, json={"provider": "openrouter", "preferred": "z-ai/glm-5.2"})

    resp = c.post(
        "/api/probe", headers=auth, json={"provider": "openrouter", "model": "z-ai/glm-5.2"}
    )

    assert resp.status_code == 200
    assert seen["params"] == {"reasoning": {"enabled": False}}
    # Reported back, so a pass is never read as "this model needs no settings".
    assert seen["notes"] and "reasoning" in seen["notes"][0]
    assert resp.json()["applied"]


# ── registry loading ────────────────────────────────────────────────────────


def test_loading_a_missing_registry_never_hands_out_the_shared_default(tmp_path):
    """Callers MUTATE what load() returns. Returning the module-level default
    object meant the first save rewrote the built-in default for the life of the
    process, so every later "what does a fresh install run?" answered with
    whatever somebody last saved. Found by two tests polluting a third."""
    from app import providers

    missing = tmp_path / "absent.json"
    first = providers.load(missing)
    first.providers["openrouter"] = providers.ProviderEntry(preferred="polluted/model")
    first.default = "openrouter"

    second = providers.load(missing)

    assert "openrouter" not in second.providers
    assert second.default == "anthropic"
    assert providers.DEFAULT_REGISTRY.default == "anthropic"
