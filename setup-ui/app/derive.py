"""One input, many env vars.

Two kinds of duplication in `.env` made first-time setup harder than the work
actually is, and both caused real outages this repo has already paid for:

  * The public tunnel hostname appears in EIGHT variables. Getting four of them
    wrong (or leaving them at a localhost default) is what silently broke the
    MCP connector: discovery advertised localhost to a remote client, and the
    audience allowlists rejected the very token the backend had just minted.
  * Supabase's project URL and publishable key each appear twice under two
    names, because the backend and the browser read different ones. `.env`
    says "Set BOTH to the same value" — which is a instruction a UI should be
    following, not a note a human has to remember.

So the setup UI collects one value per REAL decision and expands it here.
`PUBLIC_BASE_URL` is a UI-only field: it is never written to `.env`, so nothing
outside this service needs to know it exists.

`host_from_env` runs the expansion backwards. If the eight disagree — the state
this repo shipped in for weeks — the UI can say so instead of showing one of
them and implying the rest match.
"""

from __future__ import annotations

from collections import Counter

# The UI-only field. Never written to .env.
PUBLIC_BASE_URL = "PUBLIC_BASE_URL"

# Variables that are exactly the public host.
_HOST_ONLY = (
    "WEBHOOK_BASE_URL",
    "VOICE_AGENT_URL",
    "CORTEX_PUBLIC_URL",
    "MCP_JWT_ISSUER",
    "OIDC_ISSUER",
)

# Audience allowlists: the internal service-token audience plus the host. Both
# sides of the MCP handshake read one of these, and they must agree.
_AUDIENCE_VARS = ("MCP_ALLOWED_AUDIENCES", "OIDC_AUDIENCE")
_INTERNAL_AUDIENCE = "cortex-mcp"

# The MCP endpoint pasted into an assistant — host plus the transport path.
_MCP_URL_VAR = "NEXT_PUBLIC_CORTEX_MCP_URL"
_MCP_PATH = "/mcp"

#: Everything `PUBLIC_BASE_URL` writes. Rendered read-only in the UI.
PUBLIC_HOST_DERIVED: tuple[str, ...] = _HOST_ONLY + _AUDIENCE_VARS + (_MCP_URL_VAR,)

#: Same value, second name. Written whenever the source on the left changes.
MIRRORS: dict[str, tuple[str, ...]] = {
    "SUPABASE_URL": ("NEXT_PUBLIC_SUPABASE_URL",),
    "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY": ("NEXT_PUBLIC_SUPABASE_ANON_KEY",),
}

#: Every name written on someone else's behalf, so the UI can mark it read-only.
DERIVED_NAMES: frozenset[str] = frozenset(
    PUBLIC_HOST_DERIVED + tuple(t for targets in MIRRORS.values() for t in targets)
)


def normalize_host(raw: str) -> str:
    """`or.example.ai` -> `https://or.example.ai`.

    A bare host is what people type, so a missing scheme means https rather
    than an error. An explicit scheme is preserved: http is legitimate when
    pointing at localhost, and silently upgrading it would break that.
    """
    host = (raw or "").strip().rstrip("/")
    if not host:
        return ""
    if "://" not in host:
        host = f"https://{host}"
    return host


def expand_public_host(raw: str) -> dict[str, str]:
    """The full set of `.env` values implied by one public host.

    Empty input expands to nothing rather than to eight empty strings — the
    caller is clearing the field, not blanking the deployment.
    """
    host = normalize_host(raw)
    if not host:
        return {}
    audience = f"{_INTERNAL_AUDIENCE},{host}"
    out: dict[str, str] = {name: host for name in _HOST_ONLY}
    out.update({name: audience for name in _AUDIENCE_VARS})
    out[_MCP_URL_VAR] = f"{host}{_MCP_PATH}"
    return out


def _host_of(name: str, value: str) -> str:
    """Reverse one derived value back to the host it came from."""
    value = (value or "").strip()
    if not value:
        return ""
    if name in _AUDIENCE_VARS:
        # "cortex-mcp,https://host" — take the first entry that is a URL, so an
        # extra hand-added audience does not confuse the reading.
        for part in (p.strip() for p in value.split(",")):
            if "://" in part:
                return part.rstrip("/")
        return ""
    if name == _MCP_URL_VAR:
        base = value.rstrip("/")
        return base[: -len(_MCP_PATH)] if base.endswith(_MCP_PATH) else base
    return value.rstrip("/")


def host_from_env(env: dict[str, str]) -> tuple[str, list[str]]:
    """`(host, names_that_disagree)`.

    The host is whichever value the majority of the eight point at, so a single
    stale entry cannot rename the deployment. Anything not matching it — including
    anything unset — is reported, because an unset issuer is exactly as broken as
    a wrong one and is harder to spot.
    """
    seen = {name: _host_of(name, env.get(name, "")) for name in PUBLIC_HOST_DERIVED}
    populated = [h for h in seen.values() if h]
    if not populated:
        return "", []
    host = Counter(populated).most_common(1)[0][0]
    drifted = sorted(name for name, value in seen.items() if value != host)
    return host, drifted


def expand_changes(changes: dict[str, str]) -> dict[str, str]:
    """Turn what the UI submitted into what `.env` should contain.

    Applied before restart scoping, so the affected-service list is derived from
    the REAL variables — a composite field cannot under-restart.
    """
    out = dict(changes)
    if PUBLIC_BASE_URL in out:
        out.update(expand_public_host(out.pop(PUBLIC_BASE_URL)))
    for source, targets in MIRRORS.items():
        if source in out:
            for target in targets:
                out[target] = out[source]
    return out
