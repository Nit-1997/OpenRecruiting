"""Ask the applier sidecar to recreate services, and wait for the result.

WHY RECREATE AND NOT RESTART. docker-compose reads `env_file` at container
CREATE time. `docker restart` therefore reuses the environment baked in when the
container was made, and a saved `.env` change appears to apply while changing
nothing. This was shipped and verified wrongly once: the check confirmed the
file changed and the container bounced, but never that the PROCESS saw the new
value. Measured afterwards on a real container — created 03:34, started 20:15,
still serving the old value.

WHY A SIDECAR. Recreation over the Docker API means POST /containers/create,
which the socket proxy refuses after that call was proven to allow a privileged
container bind-mounting `/`. Rather than reopen it, setup-ui writes a request
file and a separate container with the socket runs one fixed command shape. It
has no listening port. A compromised setup-ui can already write `.env`, so
recreating this project's own services adds little; create rights would hand it
the host.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

# The applier polls once a second, and a compose recreate of several services
# is not fast. Long enough to cover a slow image start, short enough that a
# wedged applier surfaces as an error rather than a hung page.
_TIMEOUT_SECONDS = 180
_POLL_SECONDS = 1.0


class ApplyError(Exception):
    """The recreate could not be requested or did not finish. Safe to show."""


class Applier:
    def __init__(self, state_dir: str | Path):
        self._dir = Path(state_dir)
        self._request = self._dir / "apply-request.json"
        self._result = self._dir / "apply-result.json"

    @property
    def available(self) -> bool:
        """False when the state directory is missing, i.e. the sidecar was
        never wired up. Reported to the user rather than silently skipped —
        a save that restarts nothing must not look successful."""
        return self._dir.is_dir()

    async def recreate(self, services: list[str]) -> dict:
        if not services:
            return {"ok": True, "detail": "nothing to recreate", "services": ""}
        if not self.available:
            raise ApplyError(
                f"The applier state directory {self._dir} is not mounted, so "
                "configuration cannot be applied. Run "
                f"`docker compose up -d {' '.join(services)}` by hand."
            )

        request_id = uuid.uuid4().hex
        self._result.unlink(missing_ok=True)
        self._request.write_text(
            json.dumps({"id": request_id, "services": services}), encoding="utf-8"
        )

        waited = 0.0
        while waited < _TIMEOUT_SECONDS:
            await asyncio.sleep(_POLL_SECONDS)
            waited += _POLL_SECONDS
            if not self._result.exists():
                continue
            try:
                payload = json.loads(self._result.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue  # the sidecar may be mid-write
            if payload.get("id") != request_id:
                continue  # a stale result from an earlier request
            self._result.unlink(missing_ok=True)
            return payload

        raise ApplyError(
            f"The applier did not respond within {_TIMEOUT_SECONDS}s. The "
            "settings were SAVED to .env but may not be running yet — check "
            "`docker compose logs applier`, then "
            f"`docker compose up -d {' '.join(services)}`."
        )
