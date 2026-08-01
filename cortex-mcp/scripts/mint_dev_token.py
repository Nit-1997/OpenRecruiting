#!/usr/bin/env python3
"""Mint a developer access token without doing the full OAuth dance.

Use this to test the Cortex MCP from any HTTP-capable MCP client (including
ones that don't yet implement OAuth 2.1 dynamic client registration) while
bypassing the consent flow.

The token it produces is identical to what /api/v1/mcp/oauth/token would
return for the same user — same signature, same claim shape — so Cortex MCP
treats it identically. It's only the *issuance path* that's a shortcut.

Usage:
    python3 mint_dev_token.py --org acme
    python3 mint_dev_token.py --org northwind --ttl 3600
    python3 mint_dev_token.py --org-id <uuid> --user "Your Name"

Stays in dev only — the private key it signs with lives in
.env.local-stack, gitignored.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent                              # OpenRecruiting/
_BACKEND = _REPO / "backend"
_DEPLOY_ENV = _REPO / "deploy-config" / "backend-deploy" / ".env"
sys.path.insert(0, str(_BACKEND))


# Known orgs from the Cortex graph (so you can say --org acme instead of
# pasting a UUID). Extend as you onboard more tenants.
KNOWN_ORGS: dict[str, tuple[str, str]] = {
    "acme": ("8f5311b7-7427-47c0-97d1-e1e6c4c23847", "Acme"),
    "northwind": ("e6a942c5-5345-4790-9b83-c0b18d880825", "Northwind"),
}


def _load_env() -> None:
    """Read deploy-config/backend-deploy/.env into os.environ so the signer
    has its keypair. That file is populated by ec2-deploy.sh on first deploy
    (the MCP_JWT_PRIVATE_KEY_PEM line gets auto-generated)."""
    env_path = _DEPLOY_ENV
    if not env_path.exists():
        sys.exit(
            f"!! {env_path} not found. Either:\n"
            f"   - Run `bash deploy-config/backend-deploy/ec2-deploy.sh` once "
            f"to generate the key, or\n"
            f"   - Create the .env file manually with MCP_JWT_PRIVATE_KEY_PEM "
            f"and MCP_JWT_KEY_ID set."
        )
    for line in env_path.read_text().splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        # Unescape \n inside the PEM body.
        if key == "MCP_JWT_PRIVATE_KEY_PEM":
            value = value.encode("utf-8").decode("unicode_escape")
        os.environ.setdefault(key, value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--org",
        choices=list(KNOWN_ORGS),
        help="Shortname of a known org (acme, northwind).",
    )
    group.add_argument(
        "--org-id",
        help="Explicit org_id UUID — pair with --org-name for display.",
    )
    parser.add_argument(
        "--org-name",
        default="Dev Org",
        help="Display name when --org-id is supplied (default: Dev Org).",
    )
    parser.add_argument(
        "--user",
        default="Dev User",
        help="Display name for the user (default: Dev User).",
    )
    parser.add_argument(
        "--user-id",
        default="00000000-0000-0000-0000-000000000001",
        help="user UUID used as the `sub` claim (default: a fixed dev UUID).",
    )
    parser.add_argument(
        "--audience",
        default="cortex-mcp",
        help="Resource server audience (default: cortex-mcp).",
    )
    parser.add_argument(
        "--ttl",
        type=int,
        default=8 * 3600,
        help="Token TTL in seconds (default: 28800 = 8h).",
    )
    parser.add_argument(
        "--scope",
        default="cortex:read",
        help="OAuth scope (default: cortex:read).",
    )
    args = parser.parse_args()

    _load_env()

    # Sanity check that critical envs are present BEFORE importing the signer
    # so we can give a clean error.
    missing = [
        k for k in ("MCP_JWT_PRIVATE_KEY_PEM", "MCP_JWT_KEY_ID")
        if not os.environ.get(k)
    ]
    if missing:
        sys.exit(f"!! Missing env var(s): {missing}. Run bootstrap.sh.")

    # Make the backend's Settings happy with the few unrelated keys it requires.
    os.environ.setdefault("SUPABASE_URL", "http://localhost")
    os.environ.setdefault("SUPABASE_SECRET_KEY", "dev")
    os.environ.setdefault("SUPABASE_JWT_SECRET", "x" * 32)
    os.environ.setdefault("MCP_JWT_ISSUER", "http://localhost:8000")
    os.environ.setdefault("MCP_ALLOWED_AUDIENCES", "cortex-mcp")

    from app.services.mcp.jwt_signer import sign_access_token, reset_key_cache
    reset_key_cache()

    if args.org:
        org_id, org_name = KNOWN_ORGS[args.org]
    else:
        org_id, org_name = args.org_id, args.org_name

    signed = sign_access_token(
        subject=args.user_id,
        audience=args.audience,
        org_id=org_id,
        org_name=org_name,
        user_name=args.user,
        role="admin",
        scope=args.scope,
        ttl_seconds=args.ttl,
    )

    print(signed.token)
    print(file=sys.stderr)
    print(
        f"# kid={signed.kid}  aud={args.audience}  ttl={args.ttl}s  org={org_name} ({org_id})",
        file=sys.stderr,
    )
    print(
        '# Copy the token into your MCP client. For Claude Code .mcp.json:\n'
        '#   {\n'
        '#     "mcpServers": {\n'
        '#       "cortex": {\n'
        '#         "type": "http",\n'
        '#         "url": "http://localhost:8020/mcp/",\n'
        '#         "headers": {\n'
        '#           "Authorization": "Bearer <paste token here>"\n'
        '#         }\n'
        '#       }\n'
        '#     }\n'
        '#   }',
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
