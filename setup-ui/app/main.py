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

import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.applier import Applier, ApplyError
from app.auth import Auth, AuthError
from app.docker_ctl import DockerControl, DockerError
from app.envfile import atomic_write, parse, update
from app.litellm_cfg import read_aliases, set_model
from app.supabase_setup import check_schema, manual_instructions
from app import derive
from app.varmap import GROUPS, affected_services, all_variables, is_secret

ENV_PATH = Path(os.environ.get("SETUP_ENV_PATH", "/repo/.env"))
ENV_EXAMPLE_PATH = Path(os.environ.get("SETUP_ENV_EXAMPLE_PATH", "/repo/.env.example"))
LITELLM_PATH = Path(os.environ.get("SETUP_LITELLM_PATH", "/repo/litellm-config.yaml"))
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

    base = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    if not base and ENV_EXAMPLE_PATH.exists():
        base = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")

    try:
        backup = atomic_write(ENV_PATH, update(base, changes))
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
        if outcome.get("ok"):
            for result in results:
                try:
                    healthy = await docker.wait_until_ok(result["service"])
                    if not healthy:
                        result["ok"] = False
                        result["detail"] = "recreated but not healthy yet"
                except DockerError as exc:
                    result["detail"] = f"recreated; health unknown ({exc})"
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


class ModelBody(BaseModel):
    alias: str
    model: str


@app.get("/api/models", dependencies=[Depends(require_auth)])
async def models() -> dict:
    """The 27 per-workload aliases, as they are configured right now.

    This is what the gateway migration was for — each workload independently
    repointable. Surfacing it is the difference between "you can change the
    model" and "you can change the model if you know YAML and which of 27
    aliases the screening agent uses".
    """
    if not LITELLM_PATH.exists():
        return {"error": f"{LITELLM_PATH} not found", "aliases": []}
    aliases = read_aliases(LITELLM_PATH.read_text(encoding="utf-8"))
    return {
        "error": "",
        "aliases": [
            {
                "name": a.name,
                "model": a.model,
                "provider": a.provider,
                "supports_tools": a.supports_tools,
                "drops_temperature": a.drops_temperature,
                "description": a.description,
            }
            for a in aliases
        ],
    }


@app.post("/api/models", dependencies=[Depends(require_auth)])
async def set_alias_model(body: ModelBody) -> dict:
    """Repoint one alias and reload the gateway.

    Only litellm restarts: it is the single reader of this file, and every other
    service reaches models through it by alias. That is precisely the property
    the migration bought.
    """
    if not body.model.strip():
        raise HTTPException(status_code=400, detail="Model cannot be empty.")
    if not LITELLM_PATH.exists():
        raise HTTPException(status_code=500, detail=f"{LITELLM_PATH} not found")

    text = LITELLM_PATH.read_text(encoding="utf-8")
    try:
        updated = set_model(text, body.alias, body.model.strip())
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    warning = ""
    alias = next((a for a in read_aliases(updated) if a.name == body.alias), None)
    if alias:
        if alias.supports_tools and alias.provider == "ollama_chat":
            warning = (
                f"{body.alias} sends tools, and local models rarely support native "
                "function calling. If this alias serves a streaming workload it will "
                "silently stop recording answers rather than degrade."
            )
        elif alias.provider == "openai" and not alias.drops_temperature:
            warning = (
                f"{body.alias} now points at OpenAI but does not drop `temperature`. "
                "Nine call sites send temperature=0 and GPT-5 models accept only the "
                "default, so those calls will 400 until "
                'additional_drop_params: ["temperature"] is added.'
            )

    try:
        backup = atomic_write(LITELLM_PATH, updated)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not write config: {exc}") from exc

    try:
        await docker.restart("litellm")
        ok = await docker.wait_until_ok("litellm")
        detail = "" if ok else "restarted but not healthy yet"
    except DockerError as exc:
        ok, detail = False, str(exc)

    return {"alias": body.alias, "model": body.model.strip(),
            "backup": backup.name if backup else None,
            "restarted": ok, "detail": detail, "warning": warning}


@app.get("/healthz")
async def healthz() -> dict:
    """Unauthenticated liveness, for compose. Reveals nothing."""
    return {"status": "ok"}


# ── static ──────────────────────────────────────────────────────────────────

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
