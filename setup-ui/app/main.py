"""setup-ui — configure a self-hosted OpenRecruiting from a browser.

Boots with no dependencies of its own so it is reachable on a completely
unconfigured stack: that is the whole point, and it is why this service imports
no application code and never touches Supabase at import time.

Security posture, in order of how much weight each carries:
  1. bound to 127.0.0.1 (see docker-compose.yml) — not reachable from a network;
  2. a password set on first visit, rate limited;
  3. the Docker socket reached only through a scope-restricted proxy;
  4. secrets are write-only — the API returns whether a value is set, never the
     value itself.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.applier import Applier, ApplyError
from app.auth import Auth, AuthError
from app.docker_ctl import DockerControl, DockerError
from app.envfile import atomic_write, parse, update
from app.litellm_cfg import read_aliases
from app.probe import ProbeError, Prober
from app.readiness import evaluate as evaluate_readiness
from app.supabase_setup import check_schema, manual_instructions
from app import catalogue, derive, litellm_gen, providers, quirks, workloads
from app.varmap import GROUPS, affected_services, all_variables, is_secret

ENV_PATH = Path(os.environ.get("SETUP_ENV_PATH", "/repo/.env"))
ENV_EXAMPLE_PATH = Path(os.environ.get("SETUP_ENV_EXAMPLE_PATH", "/repo/.env.example"))
LITELLM_PATH = Path(os.environ.get("SETUP_LITELLM_PATH", "/repo/litellm-config.yaml"))
#: Which provider and model this deployment chose. No secrets — keys stay in
#: .env. Absent means the built-in defaults, so a fresh clone behaves exactly as
#: it did before providers were configurable.
REGISTRY_PATH = Path(os.environ.get("SETUP_REGISTRY_PATH", "/repo/llm-providers.json"))
STATE_PATH = Path(os.environ.get("SETUP_STATE_PATH", "/state/password.json"))
DOCKER_PROXY = os.environ.get("SETUP_DOCKER_PROXY", "http://socket-proxy:2375")
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="OpenRecruiting Setup", docs_url=None, redoc_url=None)
auth = Auth(STATE_PATH)
docker = DockerControl(DOCKER_PROXY)
# RECREATES services. Restarting is not enough — env_file is read at container
# create time, so a restart reuses the old environment. See app/applier.py.
applier = Applier(STATE_PATH.parent)


def _read_env() -> dict[str, str]:
    """The user's .env, layered over .env.example's documented defaults.

    Layered rather than either/or, because an existing deployment's .env
    predates any setting added later: reading it alone shows blanks for
    everything new, and reading only the example would discard the user's real
    values. This way their values always win and a newly documented default —
    EMAIL_PROVIDER=zoho, a base URL — still appears instead of an empty box the
    user has to research.

    Nothing here is written back. A default only becomes real in .env if the
    user saves it.
    """
    values: dict[str, str] = {}
    if ENV_EXAMPLE_PATH.exists():
        values.update(parse(ENV_EXAMPLE_PATH.read_text(encoding="utf-8")))
    if ENV_PATH.exists():
        values.update(parse(ENV_PATH.read_text(encoding="utf-8")))
    return values


def _env_base() -> str:
    """The text a write to `.env` should start from.

    `.env.example` when there is no `.env` yet, because the example is the only
    place several documented defaults live and a first write that starts from an
    empty string drops every one of them permanently — `.env` then exists, so
    this fallback never fires again.
    """
    if ENV_PATH.exists():
        return ENV_PATH.read_text(encoding="utf-8")
    if ENV_EXAMPLE_PATH.exists():
        return ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    return ""


def require_auth(request: Request) -> None:
    token = request.headers.get("x-setup-token")
    if not auth.verify(token):
        raise HTTPException(status_code=401, detail="Not signed in.")


# ── auth ────────────────────────────────────────────────────────────────────

class PasswordBody(BaseModel):
    password: str


@app.get("/api/session")
async def session_state() -> dict:
    return {"needs_setup": auth.needs_setup()}


@app.post("/api/password")
async def create_password(body: PasswordBody) -> dict:
    try:
        return {"token": auth.set_password(body.password)}
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/login")
async def login(body: PasswordBody) -> dict:
    try:
        return {"token": auth.login(body.password)}
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


# ── config ──────────────────────────────────────────────────────────────────

@app.get("/api/config", dependencies=[Depends(require_auth)])
async def get_config() -> dict:
    """Grouped settings. A secret's VALUE never leaves this process — the client
    is told only whether one is set, which is all the UI needs to render
    `•••• set` with Replace/Clear."""
    values = _read_env()
    host, drift = derive.host_from_env(values)
    groups = []
    for group in GROUPS:
        variables = []
        # One field per real decision. The public address is synthesised into
        # Get started rather than stored, so the eight variables it writes cannot
        # drift apart again — see app/derive.py.
        if group.tier == "start":
            variables.append(
                {
                    "name": derive.PUBLIC_BASE_URL,
                    "label": "Public address",
                    "help": (
                        "Your tunnel or domain, e.g. or.example.ai — https:// is "
                        "assumed. Writes the "
                        f"{len(derive.PUBLIC_HOST_DERIVED)} settings under "
                        "'Written from Get started'. Leave blank to run "
                        "localhost-only: meeting capture and remote MCP clients "
                        "both need a public address."
                    ),
                    "secret": False,
                    "required": False,
                    "services": affected_services(list(derive.PUBLIC_HOST_DERIVED)),
                    "set": bool(host),
                    "value": host,
                    "readonly": False,
                    "derives": derive.expand_public_host(host) if host else {},
                    "drift": drift,
                }
            )
        for var in group.variables:
            raw = values.get(var.name, "")
            variables.append(
                {
                    "name": var.name,
                    "label": var.label,
                    "help": var.help,
                    "secret": var.secret,
                    "required": var.required,
                    "services": var.services,
                    "set": bool(raw),
                    "value": "" if var.secret else raw,
                    # Written on another field's behalf. Shown so a value can be
                    # confirmed, not edited — two sources of truth is the bug.
                    "readonly": var.name in derive.DERIVED_NAMES,
                }
            )
        groups.append(
            {
                "id": group.id,
                "title": group.title,
                "blurb": group.blurb,
                "tier": group.tier,
                "missing_required": [
                    v["name"] for v in variables if v["required"] and not v["set"]
                ],
                "variables": variables,
            }
        )
    return {"groups": groups}


class SaveBody(BaseModel):
    changes: dict[str, str]


@app.post("/api/plan", dependencies=[Depends(require_auth)])
async def plan(body: SaveBody) -> dict:
    """What a save WOULD do. Nothing is written.

    Restarting is disruptive — an in-flight voice call dies — so the user sees
    the exact container list and confirms before anything happens.
    """
    # Expand FIRST. The composite public-address field is not a real variable, so
    # validating before expansion would reject it, and scoping restarts from it
    # would under-restart: the services that matter belong to the eight it writes.
    changes = derive.expand_changes(body.changes)
    unknown = sorted(set(changes) - all_variables())
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown settings: {unknown}")
    services = affected_services(list(changes))
    return {
        "changes": sorted(changes),
        "restarts": services,
        "warning": (
            "Restarting voice-agent ends any call in progress."
            if "voice-agent" in services
            else ""
        ),
    }


@app.post("/api/apply", dependencies=[Depends(require_auth)])
async def apply(body: SaveBody) -> JSONResponse:
    # Same expansion as /api/plan, so what is applied is what was previewed.
    changes = derive.expand_changes(body.changes)
    unknown = sorted(set(changes) - all_variables())
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown settings: {unknown}")
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to save.")

    try:
        backup = atomic_write(ENV_PATH, update(_env_base(), changes))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not write .env: {exc}") from exc

    services = affected_services(list(changes))
    results = []
    try:
        # RECREATE, not restart. A restart reuses the environment baked in when
        # the container was created, so the save would appear to work and change
        # nothing at all.
        outcome = await applier.recreate(services)
        for service in services:
            results.append({
                "service": service,
                "ok": bool(outcome.get("ok")),
                "detail": "" if outcome.get("ok") else str(outcome.get("detail", "")),
            })
        # Health is checked separately: compose reports the recreate succeeded,
        # which is not the same as the service coming back up.
        #
        # CONCURRENTLY, and that is not a tuning choice. These ran in a loop, each
        # waiting up to 90s, so the wait was the SUM of every service's timeout:
        # a Supabase change touches 11 services, which is 990s of polling inside
        # one HTTP request that has sent no bytes. Every real save on a first run
        # hit it, because containers that are not configured yet are exactly the
        # ones that never come up — so each one burned its full 90s. Browsers and
        # proxies drop an idle request long before that, and the page reported
        # `NetworkError when attempting to fetch resource`, which reads like the
        # save failed. It had not: .env is written above, before any of this.
        #
        # Waiting in parallel makes the cost the SLOWEST service rather than the
        # sum, so the same 11-service save waits ~90s at worst.
        if outcome.get("ok"):
            async def _health(result: dict) -> None:
                try:
                    if not await docker.wait_until_ok(result["service"]):
                        result["ok"] = False
                        result["detail"] = "recreated but not healthy yet"
                except DockerError as exc:
                    result["detail"] = f"recreated; health unknown ({exc})"

            # return_exceptions so one unexpected failure cannot discard the
            # results of the other ten — which services came back is the whole
            # answer the user is waiting for.
            for service, outcome_or_error in zip(
                results,
                await asyncio.gather(
                    *(_health(r) for r in results), return_exceptions=True
                ),
            ):
                if isinstance(outcome_or_error, BaseException):
                    service["ok"] = False
                    service["detail"] = f"health check failed: {outcome_or_error}"
    except ApplyError as exc:
        results = [{"service": s, "ok": False, "detail": str(exc)} for s in services]

    return JSONResponse(
        {
            # The expanded list: one public-address edit reports the eight names
            # actually written, so the confirmation matches the file.
            "saved": sorted(changes),
            "backup": backup.name if backup else None,
            "restarts": results,
        }
    )


# ── health ──────────────────────────────────────────────────────────────────

@app.get("/api/health", dependencies=[Depends(require_auth)])
async def health() -> dict:
    try:
        containers = await docker.list_containers()
    except DockerError as exc:
        return {"error": str(exc), "services": []}
    return {
        "error": "",
        "services": [
            {"name": c.name, "state": c.state, "health": c.health, "ok": c.ok}
            for c in containers
        ],
    }


@app.get("/api/database", dependencies=[Depends(require_auth)])
async def database() -> dict:
    """Whether the Supabase project is provisioned.

    Read-only by necessity, not by choice: the service key can detect the schema
    but cannot run DDL, so this reports status and hands over exact steps rather
    than pretending to apply it. See app/supabase_setup.py for the measurement
    behind that.
    """
    values = _read_env()
    status = await check_schema(values.get("SUPABASE_URL", ""), values.get("SUPABASE_SECRET_KEY", ""))
    return {
        "state": status.state,
        "detail": status.detail,
        "steps": [] if status.ready else manual_instructions(values.get("SUPABASE_URL", "")),
    }


@app.get("/api/readiness", dependencies=[Depends(require_auth)])
async def readiness() -> dict:
    """Which features are live, and what is still missing for the rest.

    Derived purely from `.env`, so it answers "have I finished configuring
    this?" — not "is it working right now?". Container state is /api/health and
    schema state is /api/database; a feature can be `live` here while a
    container is down.
    """
    # The registry is passed in, not read inside: readiness stays a pure function
    # of its arguments, and "is the chosen provider's key set" cannot be answered
    # without knowing which provider was chosen.
    features = evaluate_readiness(_read_env(), _load_registry())
    return {
        "features": [
            {
                "id": f.id,
                "name": f.name,
                "state": f.state,
                "missing": f.missing,
                "consequence": f.consequence,
                "required": f.required,
                "doc": f.doc,
            }
            for f in features
        ]
    }


# ── model providers ─────────────────────────────────────────────────────────
# The AI setup, in one place: choose a provider, give it a key and a preferred
# model, and every workload follows it. Before this, the only provider fields
# were two hardcoded keys and the only way to change a model was a YAML file.


async def _catalogue_for(registry: providers.Registry) -> tuple[dict, list[str]]:
    """Metadata for every configured provider, best effort, plus who failed.

    Best effort ON PURPOSE: a catalogue outage must not block a save. But it must
    not be SILENT either, which is what returning only the merged dict made it.
    Quirk derivation without metadata falls back to provider-level constants,
    and for a reasoning model that means the `reasoning` quirk is simply absent —
    the exact empty-reply failure quirks.py exists to prevent, written into the
    config by a save that reported success. The labels come back so the caller
    can say so out loud.
    """
    merged: dict = {}
    degraded: list[str] = []
    for provider_id in registry.providers:
        try:
            merged.update(await catalogue.fetch(provider_id))
        except catalogue.CatalogueError:
            degraded.append(providers.PROVIDERS[provider_id].label)
    return merged, degraded


#: Said when a save had to render without catalogue metadata. Deliberately
#: concrete about the consequence: "metadata unavailable" reads as cosmetic.
_DEGRADED_WARNING = (
    "Saved, but the model list for {names} could not be fetched, so per-model "
    "compatibility settings were left out of the gateway config. A reasoning "
    "model configured this way can spend its whole token budget thinking and "
    "return an empty reply. Save again once the provider is reachable to write "
    "the full settings."
)


async def _write_and_reload(
    registry: providers.Registry, *, recreate: bool = False
) -> dict:
    """Persist the registry, regenerate the gateway config, reload the gateway.

    ONLY litellm reloads. It is the single reader of that file and every other
    service reaches models through it by alias — the property the gateway
    migration bought, and the reason changing every model in the deployment does
    not disturb a call in progress.

    `recreate` picks HOW. A restart is enough for a config-file change, which the
    container re-reads on boot. It is NOT enough when `.env` changed, because
    env_file is read at container create time — so the caller that just wrote a
    key asks for a recreate here rather than letting this restart first and then
    recreating on top of it, which reloaded the gateway twice and made the user
    wait through both.
    """
    catalogue_data, degraded = await _catalogue_for(registry)
    try:
        rendered = litellm_gen.render(registry, catalogue_data)
    except (providers.RegistryError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        atomic_write(REGISTRY_PATH, json.dumps(providers.to_dict(registry), indent=2) + "\n")
        backup = atomic_write(LITELLM_PATH, rendered)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not write config: {exc}") from exc

    if recreate:
        try:
            outcome = await applier.recreate(["litellm"])
            ok = bool(outcome.get("ok"))
            detail = "" if ok else str(outcome.get("detail", ""))
            # compose reporting the recreate succeeded is NOT the gateway coming
            # back up. Reporting "restarted" off the exit status alone is how a
            # litellm that never came healthy gets announced as fine.
            if ok and not await docker.wait_until_ok("litellm"):
                ok, detail = False, "recreated but not healthy yet"
        except (ApplyError, DockerError) as exc:
            ok, detail = False, str(exc)
    else:
        try:
            await docker.restart("litellm")
            ok = await docker.wait_until_ok("litellm")
            detail = "" if ok else "restarted but not healthy yet"
        except DockerError as exc:
            ok, detail = False, str(exc)

    return {
        "restarted": ok,
        "detail": detail,
        "backup": backup.name if backup else None,
        "degraded": _DEGRADED_WARNING.format(names=", ".join(degraded)) if degraded else "",
    }


async def _supports_tools(spec: providers.ProviderSpec, model_id: str) -> bool:
    """Whether this model does NATIVE function calling, catalogue first.

    Falls back to the provider-level constant when no catalogue can answer, which
    is the same fallback the generator uses — so this cannot disagree with what
    gets written into the config.
    """
    try:
        metadata = (await catalogue.fetch(spec.id)).get(f"{spec.id}/{model_id}")
    except catalogue.CatalogueError:
        metadata = None
    return quirks.derive(spec, model_id, metadata).supports_tools


async def _binding_warning(registry: providers.Registry) -> str:
    """Said when the DEFAULT provider's model cannot call tools natively.

    A warning rather than a refusal, unlike the per-alias pin below: choosing a
    local model for everything is a legitimate thing to want, and blocking it
    would make an all-Ollama deployment unreachable. But three workloads stream
    AND send tools, and those do not degrade on such a model — they stop
    recording answers — so it cannot pass without being said.
    """
    spec = providers.PROVIDERS.get(registry.default)
    entry = registry.providers.get(registry.default)
    if spec is None or entry is None:
        return ""
    model_id = entry.preferred
    if await _supports_tools(spec, model_id):
        return ""
    return (
        f"{spec.label}'s {model_id} does not call tools natively, so tools are "
        "emulated in the prompt. That breaks "
        f"{', '.join(sorted(workloads.STREAMING_TOOL_ALIASES))} outright rather "
        "than degrading them — they stream and send tools at the same time, and "
        "emulated tools do not compose with streaming. Pin those three to a "
        "tool-capable model under Models per task."
    )


def _load_registry() -> providers.Registry:
    try:
        return providers.load(REGISTRY_PATH)
    except providers.RegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class ProviderBody(BaseModel):
    provider: str
    preferred: str
    fast: str = ""
    #: Write-only, like every other secret here. Omit to leave the stored key
    #: alone — the UI shows `•••• set` and never receives it back.
    api_key: str = ""
    make_default: bool = False


@app.get("/api/providers", dependencies=[Depends(require_auth)])
async def list_providers() -> dict:
    registry = _load_registry()
    values = _read_env()
    return {
        "default": registry.default,
        "available": [
            {
                "id": spec.id,
                "label": spec.label,
                "needs_key": bool(spec.key_var),
                "key_var": spec.key_var or "",
                "default_preferred": spec.default_preferred,
                "default_fast": spec.default_fast,
                "has_catalogue": bool(spec.catalogue_url),
            }
            for spec in providers.PROVIDERS.values()
        ],
        "configured": [
            {
                "id": pid,
                "label": providers.PROVIDERS[pid].label,
                "preferred": entry.preferred,
                "fast": entry.fast,
                "is_default": pid == registry.default,
                # Whether the credential this provider needs is actually present.
                # The failure this whole feature exists to prevent is a provider
                # that looks configured while its key is empty or belongs to
                # someone else, so "set" is reported per provider, not globally.
                "key_set": (
                    True
                    if not providers.PROVIDERS[pid].key_var
                    else bool(values.get(providers.PROVIDERS[pid].key_var, ""))
                ),
            }
            for pid, entry in registry.providers.items()
        ],
    }


@app.post("/api/providers", dependencies=[Depends(require_auth)])
async def upsert_provider(body: ProviderBody) -> dict:
    spec = providers.PROVIDERS.get(body.provider)
    if spec is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{body.provider}'.")
    if not body.preferred.strip():
        raise HTTPException(status_code=400, detail="A preferred model is required.")

    registry = _load_registry()
    registry.providers[body.provider] = providers.ProviderEntry(
        preferred=body.preferred.strip(), fast=body.fast.strip()
    )
    if body.make_default or len(registry.providers) == 1:
        # First one added becomes the default, as asked. Also covers the case
        # where the previous default was just deleted.
        registry.default = body.provider

    wrote_key = bool(body.api_key.strip() and spec.key_var)
    if wrote_key:
        # The SAME two-step base as /api/apply, and for the same reason. This
        # card renders above the settings groups, so on a fresh clone that never
        # copied .env.example it is the first thing that writes .env — and
        # starting from "" produced a one-line file holding nothing but the key.
        # Every service mounts that file, so every documented default in the
        # example (LLM_GATEWAY_URL among them) would simply be gone, and
        # /api/apply's own example fallback never fires again because .env now
        # exists.
        base = _env_base()
        try:
            atomic_write(ENV_PATH, update(base, {spec.key_var: body.api_key.strip()}))
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Could not write .env: {exc}") from exc

    # The key lives in .env, which litellm reads via env_file — and env_file is
    # read at container CREATE time, so a restart would reuse the old value and
    # the save would appear to work while changing nothing. Recreate instead.
    # Asked for up front rather than bolted on afterwards: doing both meant the
    # gateway went down, came up, and went down again while the user waited.
    result = await _write_and_reload(registry, recreate=wrote_key)
    warning = await _binding_warning(registry)
    return {
        "provider": body.provider,
        "default": registry.default,
        "warning": warning,
        **result,
    }


@app.delete("/api/providers/{provider_id}", dependencies=[Depends(require_auth)])
async def delete_provider(provider_id: str) -> dict:
    registry = _load_registry()
    if provider_id not in registry.providers:
        raise HTTPException(status_code=404, detail=f"'{provider_id}' is not configured.")
    if len(registry.providers) == 1:
        raise HTTPException(
            status_code=400,
            detail="This is the only provider. Add another before removing it, or "
            "every workload would have nowhere to run.",
        )
    registry.providers.pop(provider_id)
    # Overrides pointing at a provider that no longer exists would fail the next
    # render, so they go with it rather than leaving the file unrenderable.
    dropped = [a for a, o in registry.overrides.items() if o["provider"] == provider_id]
    for alias in dropped:
        registry.overrides.pop(alias)
    if registry.default == provider_id:
        registry.default = next(iter(registry.providers))

    result = await _write_and_reload(registry)
    # Removing the default promotes whichever provider happens to be first, and
    # that can be Ollama — which cannot call tools. Same warning as the add path;
    # the user did not pick this default, so it matters more here, not less.
    return {"removed": provider_id, "default": registry.default,
            "dropped_overrides": dropped,
            "warning": await _binding_warning(registry), **result}


@app.get("/api/providers/{provider_id}/catalogue", dependencies=[Depends(require_auth)])
async def provider_catalogue(provider_id: str) -> dict:
    try:
        models = await catalogue.fetch(provider_id)
    except catalogue.CatalogueError as exc:
        return {"error": str(exc), "models": []}
    return {"error": "", "models": catalogue.summarise(provider_id, models)}


class ProbeBody(BaseModel):
    provider: str
    model: str


@app.post("/api/probe", dependencies=[Depends(require_auth)])
async def probe_model(body: ProbeBody) -> dict:
    """Make a model actually do the four things this stack needs.

    Metadata says what a model claims; this says what it does. Reached through
    the gateway's wildcard route, so a model can be tested BEFORE it is saved and
    no provider key ever enters this process.
    """
    spec = providers.PROVIDERS.get(body.provider)
    if spec is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{body.provider}'.")
    if not body.model.strip():
        raise HTTPException(status_code=400, detail="A model id is required.")

    values = _read_env()
    if spec.key_var and not values.get(spec.key_var, ""):
        raise HTTPException(
            status_code=400,
            detail=f"{spec.label} has no key set, so there is nothing to test with. "
            f"Save {spec.key_var} first.",
        )
    # The probe rides the gateway's wildcard route, and that route only exists
    # for providers already in the generated config. Testing a model of a
    # provider you have not added yet fails deep inside litellm as "no healthy
    # deployments", which tells the user nothing about what to do next.
    if body.provider not in _load_registry().providers:
        raise HTTPException(
            status_code=400,
            detail=f"Add {spec.label} first, then test. The gateway only routes to "
            "providers it has been told about — press Add + and the test will work.",
        )

    # The same quirks the generator would write for this model. Without them the
    # probe measures a configuration that will never run — see probe.py.
    model_id = body.model.strip()
    try:
        metadata = (await catalogue.fetch(spec.id)).get(f"{spec.id}/{model_id}")
    except catalogue.CatalogueError:
        metadata = None
    derived = quirks.derive(spec, model_id, metadata)

    prober = Prober(
        values.get("LLM_GATEWAY_URL", "") or "http://litellm:4000",
        values.get("LITELLM_MASTER_KEY", ""),
    )
    try:
        result = await prober.run(
            spec.prefix, spec.id, model_id, derived.params, derived.notes
        )
    except ProbeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.as_dict()


class OverrideBody(BaseModel):
    alias: str
    provider: str = ""
    model: str = ""


@app.get("/api/models", dependencies=[Depends(require_auth)])
async def models() -> dict:
    """Every workload alias, and what it currently resolves to.

    This is what the gateway migration was for — each workload independently
    repointable. Surfacing it is the difference between "you can change the
    model" and "you can change the model if you know YAML and which of 27
    aliases the screening agent uses".
    """
    registry = _load_registry()
    live = {}
    if LITELLM_PATH.exists():
        live = {a.name: a for a in read_aliases(LITELLM_PATH.read_text(encoding="utf-8"))}

    rows = []
    for workload in workloads.WORKLOADS:
        override = registry.overrides.get(workload.name)
        alias = live.get(workload.name)
        rows.append(
            {
                "name": workload.name,
                "tier": workload.tier,
                "description": workload.comment.replace("\n", " "),
                "model": alias.model if alias else "",
                "supports_tools": alias.supports_tools if alias else None,
                "override": override or None,
                # A model with no native tool calling does not degrade these, it
                # breaks them: emulated tools and streaming do not compose.
                "streams_tools": workload.name in workloads.STREAMING_TOOL_ALIASES,
            }
        )
    return {"error": "", "default": registry.default, "aliases": rows}


@app.post("/api/models", dependencies=[Depends(require_auth)])
async def set_alias_override(body: OverrideBody) -> dict:
    """Pin one workload to a specific provider and model, or clear the pin.

    An empty provider clears the override, so the workload goes back to following
    the default. That is the escape hatch for the one workload that needs a
    different model without turning the other 21 into hand-managed entries.
    """
    workload = workloads.by_name().get(body.alias)
    if workload is None:
        raise HTTPException(status_code=400, detail=f"No workload named '{body.alias}'.")

    registry = _load_registry()
    if not body.provider.strip():
        registry.overrides.pop(body.alias, None)
    else:
        # The generator pins every local-tier alias to Ollama before it ever
        # consults overrides, so one saved here persisted, came back from
        # GET /api/models, painted the row "pinned" — and changed nothing in the
        # gateway, forever. These aliases exist precisely to BE the local A/B
        # arm of a comparison (see workloads.py), so the honest answer is that
        # they cannot be repointed, not that the pin quietly evaporates.
        if workload.tier == "local":
            raise HTTPException(
                status_code=400,
                detail=f"'{body.alias}' is a local A/B variant and always runs on "
                "Ollama — that is what it is for. Change Ollama's model under AI "
                "models to move it, or pin the non-local alias beside it.",
            )
        if body.provider not in registry.providers:
            raise HTTPException(
                status_code=400,
                detail=f"'{body.provider}' is not configured. Add it under AI models first.",
            )
        if not body.model.strip():
            raise HTTPException(status_code=400, detail="A model id is required.")
        # The refusal workloads.py has always claimed the UI makes. These three
        # stream AND send tools; a model without native function calling does not
        # degrade them, it stops them recording answers, because llm-core's
        # stream_turn injects the emulated schema and never parses the reply back.
        # A warning is not enough for a failure with no error anywhere.
        spec = providers.PROVIDERS[body.provider]
        if body.alias in workloads.STREAMING_TOOL_ALIASES and not await _supports_tools(
            spec, body.model.strip()
        ):
            raise HTTPException(
                status_code=400,
                detail=f"'{body.alias}' streams and sends tools at the same time, and "
                f"{body.model.strip()} does not call tools natively — they would be "
                "emulated in the prompt, which does not compose with streaming. This "
                "workload would stop recording answers with no error anywhere. Pick a "
                "tool-capable model.",
            )
        registry.overrides[body.alias] = {
            "provider": body.provider,
            "model": body.model.strip(),
        }

    result = await _write_and_reload(registry)
    return {"alias": body.alias, "override": registry.overrides.get(body.alias), **result}


@app.get("/healthz")
async def healthz() -> dict:
    """Unauthenticated liveness, for compose. Reveals nothing."""
    return {"status": "ok"}


# ── static ──────────────────────────────────────────────────────────────────

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
