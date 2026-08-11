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

from app.auth import Auth, AuthError
from app.docker_ctl import DockerControl, DockerError
from app.envfile import atomic_write, parse, update
from app.supabase_setup import check_schema, manual_instructions
from app.varmap import GROUPS, affected_services, all_variables, is_secret

ENV_PATH = Path(os.environ.get("SETUP_ENV_PATH", "/repo/.env"))
ENV_EXAMPLE_PATH = Path(os.environ.get("SETUP_ENV_EXAMPLE_PATH", "/repo/.env.example"))
STATE_PATH = Path(os.environ.get("SETUP_STATE_PATH", "/state/password.json"))
DOCKER_PROXY = os.environ.get("SETUP_DOCKER_PROXY", "http://socket-proxy:2375")
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="OpenRecruiting Setup", docs_url=None, redoc_url=None)
auth = Auth(STATE_PATH)
docker = DockerControl(DOCKER_PROXY)


def _read_env() -> dict[str, str]:
    if ENV_PATH.exists():
        return parse(ENV_PATH.read_text(encoding="utf-8"))
    if ENV_EXAMPLE_PATH.exists():
        # First run with no .env at all: seed the form from the example so the
        # user sees the documented defaults rather than 43 blank fields.
        return parse(ENV_EXAMPLE_PATH.read_text(encoding="utf-8"))
    return {}


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
    groups = []
    for group in GROUPS:
        variables = []
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
                }
            )
        groups.append(
            {
                "id": group.id,
                "title": group.title,
                "blurb": group.blurb,
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
    unknown = sorted(set(body.changes) - all_variables())
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown settings: {unknown}")
    services = affected_services(list(body.changes))
    return {
        "changes": sorted(body.changes),
        "restarts": services,
        "warning": (
            "Restarting voice-agent ends any call in progress."
            if "voice-agent" in services
            else ""
        ),
    }


@app.post("/api/apply", dependencies=[Depends(require_auth)])
async def apply(body: SaveBody) -> JSONResponse:
    unknown = sorted(set(body.changes) - all_variables())
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown settings: {unknown}")
    if not body.changes:
        raise HTTPException(status_code=400, detail="Nothing to save.")

    base = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    if not base and ENV_EXAMPLE_PATH.exists():
        base = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")

    try:
        backup = atomic_write(ENV_PATH, update(base, body.changes))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not write .env: {exc}") from exc

    results = []
    for service in affected_services(list(body.changes)):
        try:
            await docker.restart(service)
            ok = await docker.wait_until_ok(service)
            results.append({"service": service, "ok": ok,
                            "detail": "" if ok else "restarted but not healthy yet"})
        except DockerError as exc:
            results.append({"service": service, "ok": False, "detail": str(exc)})

    return JSONResponse(
        {
            "saved": sorted(body.changes),
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


@app.get("/healthz")
async def healthz() -> dict:
    """Unauthenticated liveness, for compose. Reveals nothing."""
    return {"status": "ok"}


# ── static ──────────────────────────────────────────────────────────────────

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
