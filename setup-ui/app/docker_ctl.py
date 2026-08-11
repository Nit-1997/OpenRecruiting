"""Restart containers through a scope-restricted proxy, never the raw socket.

`/var/run/docker.sock` is root-equivalent on the host: anything that can reach it
can start a privileged container bind-mounting `/`. Handing that to a web service
that also holds every secret in the deployment would make a single bug in this
UI a full host compromise.

So `setup-ui` never sees the socket. A `wollomatic/socket-proxy` sidecar does,
with a regex allowlist permitting exactly two calls: GET `/containers/json` and
POST `/containers/<id>/restart`. Everything else — create, exec, images,
volumes, networks, kill, delete — is refused with 403 by a process that has no
other HTTP surface. That is what makes "write .env and restart" defensible
rather than reckless.

`tecnativa/docker-socket-proxy` was the first choice and is NOT safe here: its
`POST=1` flag is a blanket allow across every enabled path group, so
`POST /containers/create` is permitted. Measured against the running proxy, not
assumed — a well-formed privileged create with `"Binds": ["/:/host"]` returned
201 and the container really was created. Do not switch back.

Every call has a timeout. A hung Docker daemon must surface as an error in the
UI, not a spinner that never resolves.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_RESTART_TIMEOUT = 60.0

# The Docker API version prefix is REQUIRED, not cosmetic. socket-proxy's
# allowlist matches on the full path (`/v[\d\.]+/containers/json`), so an
# unversioned request is refused with 403 even though the same call is allowed.
# Pinned rather than negotiated: the two endpoints used here have been stable
# for years, and a version handshake would need its own allowlist entry.
_API = "/v1.47"


@dataclass(frozen=True)
class Container:
    name: str
    state: str
    health: str | None

    @property
    def ok(self) -> bool:
        """Healthy, or running without a healthcheck defined. A container with
        no healthcheck cannot report health, and treating that as failure would
        mark half the stack broken."""
        if self.state != "running":
            return False
        return self.health in (None, "healthy")


class DockerError(Exception):
    """Talking to the proxy failed. Safe to show a user."""


class DockerControl:
    def __init__(self, base_url: str, project: str = "openrecruiting"):
        self._base = base_url.rstrip("/")
        self._project = project

    async def _get(self, path: str, **params) -> object:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(f"{self._base}{path}", params=params)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:
            raise DockerError(f"Could not reach the Docker proxy: {exc}") from exc

    async def list_containers(self) -> list[Container]:
        """Every container in this compose project, by service name."""
        raw = await self._get(f"{_API}/containers/json", all="true")
        out: list[Container] = []
        for item in raw:  # type: ignore[union-attr]
            labels = item.get("Labels") or {}
            if labels.get("com.docker.compose.project") != self._project:
                continue
            service = labels.get("com.docker.compose.service")
            if not service:
                continue
            status = item.get("Status", "")
            health = None
            if "(healthy)" in status:
                health = "healthy"
            elif "(unhealthy)" in status:
                health = "unhealthy"
            elif "(health: starting)" in status:
                health = "starting"
            out.append(Container(name=service, state=item.get("State", "unknown"), health=health))
        return sorted(out, key=lambda c: c.name)

    async def _container_id(self, service: str) -> str:
        raw = await self._get(f"{_API}/containers/json", all="true")
        for item in raw:  # type: ignore[union-attr]
            labels = item.get("Labels") or {}
            if (
                labels.get("com.docker.compose.project") == self._project
                and labels.get("com.docker.compose.service") == service
            ):
                return item["Id"]
        raise DockerError(f"No container found for service '{service}'.")

    async def restart(self, service: str) -> None:
        container_id = await self._container_id(service)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(_RESTART_TIMEOUT)) as client:
                resp = await client.post(f"{self._base}{_API}/containers/{container_id}/restart")
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise DockerError(f"Restarting {service} failed: {exc}") from exc

    async def wait_until_ok(self, service: str, timeout: float = 90.0) -> bool:
        """Poll until the container reports ok, or give up.

        Returns rather than raising on timeout: a service that comes back
        unhealthy is a result the UI must SHOW next to that service, not an
        exception that hides which of five restarts actually failed.
        """
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                for container in await self.list_containers():
                    if container.name == service:
                        if container.ok:
                            return True
                        break
            except DockerError:
                pass  # transient while the daemon works; the deadline still applies
            await asyncio.sleep(2.0)
        return False
