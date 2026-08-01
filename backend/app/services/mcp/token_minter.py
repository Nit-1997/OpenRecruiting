"""Mint short-lived RS256 JWTs for internal callers talking to Cortex MCP.

Cortex MCP is an OAuth resource server: it only trusts JWTs signed by the
shared MCP keypair and verified against the public JWKS published by the v1
backend at http://localhost:8004/.well-known/jwks.json.

For this minter to produce tokens Cortex will accept, v2 MUST be configured
with the SAME MCP_JWT_PRIVATE_KEY_PEM and MCP_JWT_KEY_ID as v1 (so the `kid`
in the token header matches a key in v1's JWKS), and MCP_JWT_ISSUER must equal
Cortex's expected issuer (http://localhost:8004 in production).

This is the machine-to-machine sibling of the user-facing OAuth flow in
`app.api.v2.routers.mcp_oauth`. Both sign through `jwt_signer.sign_access_token`,
so there is a single signing path.
"""

from __future__ import annotations

from app.config import get_settings
from app.services.mcp.jwt_signer import sign_access_token

CORTEX_AUDIENCE = "cortex-mcp"
CORTEX_SCOPE = "cortex:read"
# Fixed service-principal identity for machine callers (e.g. the intake
# context-builder Lambda). Cortex only requires `sub` to be present; it is not
# resolved to a real user.
SERVICE_PRINCIPAL_SUB = "00000000-0000-0000-0000-0000000000fa"


def mint_cortex_service_token(
    *,
    org_id: str,
    org_name: str,
    ttl_seconds: int = 300,
) -> tuple[str, int]:
    """Mint a short-lived cortex:read token bound to `org_id`.

    Returns (token, expires_in_seconds). The org_id becomes the group_id that
    Cortex force-binds onto every query, so the caller cannot read another
    tenant's graph.
    """
    settings = get_settings()
    if CORTEX_AUDIENCE not in {
        a.strip() for a in settings.MCP_ALLOWED_AUDIENCES.split(",") if a.strip()
    }:
        raise RuntimeError(
            f"{CORTEX_AUDIENCE!r} is not in MCP_ALLOWED_AUDIENCES "
            f"({settings.MCP_ALLOWED_AUDIENCES!r})."
        )

    signed = sign_access_token(
        subject=SERVICE_PRINCIPAL_SUB,
        audience=CORTEX_AUDIENCE,
        org_id=org_id,
        org_name=org_name,
        user_name=None,
        role="service",
        scope=CORTEX_SCOPE,
        ttl_seconds=ttl_seconds,
    )
    return signed.token, signed.expires_in
