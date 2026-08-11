"""First-run password, session tokens, and login rate limiting.

This guards a service that holds every secret in the deployment and can restart
containers, so the bar is higher than a normal login form. Two things carry that
weight together: the service binds to 127.0.0.1 by default (so it is not
reachable from the network at all), and this password sits behind that.

Chosen over a token printed at boot because people start the stack with
`docker compose up -d`, where nothing is printed to a terminal — a token would
mean "now go run docker compose logs", which is exactly the friction this whole
effort exists to remove.

Forgotten password: delete the hash file on the volume. That requires host
access, which is the right bar for a reset on something holding a Docker socket.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

# Deliberately not bcrypt/argon2: this service must boot with zero third-party
# auth dependencies, and PBKDF2-HMAC-SHA256 at this cost is appropriate for a
# single local operator password. The dominant control is the localhost bind.
_ITERATIONS = 480_000
_TOKEN_TTL_SECONDS = 12 * 60 * 60

# Rate limiting. Small numbers on purpose — a human typing a password needs a
# handful of attempts; a script needs thousands.
_MAX_FAILURES = 5
_LOCKOUT_SECONDS = 60


class AuthError(Exception):
    """Login refused. The message is safe to show a user."""


class Auth:
    def __init__(self, state_path: str | Path):
        self._path = Path(state_path)
        self._failures: list[float] = []
        self._tokens: dict[str, float] = {}

    # -- password ---------------------------------------------------------
    def needs_setup(self) -> bool:
        return not self._path.exists()

    def set_password(self, password: str) -> str:
        """First run only. Returns a session token.

        Refuses to overwrite an existing password: whoever already claimed this
        instance owns it, and letting an unauthenticated caller reset it would
        make the password meaningless.
        """
        if not self.needs_setup():
            raise AuthError("A password is already set for this instance.")
        if len(password) < 8:
            raise AuthError("Password must be at least 8 characters.")

        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"salt": salt.hex(), "hash": digest.hex(), "iterations": _ITERATIONS}),
            encoding="utf-8",
        )
        os.chmod(self._path, 0o600)
        return self._issue_token()

    def login(self, password: str) -> str:
        if self.needs_setup():
            raise AuthError("No password has been set yet.")
        self._check_not_locked_out()

        stored = json.loads(self._path.read_text(encoding="utf-8"))
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(stored["salt"]), stored["iterations"]
        )
        # Constant-time: a timing difference here leaks the hash prefix.
        if not hmac.compare_digest(digest.hex(), stored["hash"]):
            self._failures.append(time.time())
            raise AuthError("Incorrect password.")

        self._failures.clear()
        return self._issue_token()

    def _check_not_locked_out(self) -> None:
        cutoff = time.time() - _LOCKOUT_SECONDS
        self._failures = [t for t in self._failures if t > cutoff]
        if len(self._failures) >= _MAX_FAILURES:
            raise AuthError(
                f"Too many failed attempts. Try again in {_LOCKOUT_SECONDS} seconds."
            )

    # -- sessions ---------------------------------------------------------
    def _issue_token(self) -> str:
        token = secrets.token_urlsafe(32)
        self._tokens[token] = time.time() + _TOKEN_TTL_SECONDS
        return token

    def verify(self, token: str | None) -> bool:
        """Tokens live in memory only, so a restart logs everyone out. That is
        the correct trade for a setup tool: no session store to leak, and the
        blast radius of a stolen token is one container lifetime."""
        if not token:
            return False
        expiry = self._tokens.get(token)
        if expiry is None:
            return False
        if expiry < time.time():
            del self._tokens[token]
            return False
        return True
