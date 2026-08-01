"""Discovery endpoints.

These are mounted at the ROOT of the FastAPI app, not under /api/v1, because
RFC 8414 requires the well-known path to be on the issuer origin. The root
mounting is set up in `app/main.py` via the `well_known_router` exported here.

Two endpoints:
  GET /.well-known/oauth-authorization-server  → AS metadata (RFC 8414)
  GET /.well-known/jwks.json                   → JWKS (RFC 7517)
"""
from __future__ import annotations

from fastapi import APIRouter, Response

from app.config import get_settings
from app.models.mcp import AuthServerMetadata
from app.services.mcp.jwt_signer import public_jwks


well_known_router = APIRouter()


def _base_url() -> str:
    return get_settings().MCP_JWT_ISSUER.rstrip("/")


@well_known_router.get(
    "/.well-known/oauth-authorization-server",
    response_model=AuthServerMetadata,
)
async def get_authorization_server_metadata() -> AuthServerMetadata:
    base = _base_url()
    return AuthServerMetadata(
        issuer=base,
        authorization_endpoint=f"{base}/api/v2/mcp/oauth/authorize",
        token_endpoint=f"{base}/api/v2/mcp/oauth/token",
        registration_endpoint=f"{base}/api/v2/mcp/oauth/register",
        revocation_endpoint=f"{base}/api/v2/mcp/oauth/revoke",
        jwks_uri=f"{base}/.well-known/jwks.json",
        service_documentation="http://localhost:8004/docs",
    )


@well_known_router.get("/.well-known/jwks.json")
async def get_jwks() -> Response:
    """Public keys for verifying RS256 access tokens.

    Returned with a long Cache-Control window so resource servers don't
    re-fetch on every request. Anything sensitive to rotation should set its
    own JWKS refresh policy (the Cortex MCP server caches for 10 min).

    MCP token signing is optional. With no signing key configured this reports
    503 rather than a 500 traceback, so an unconfigured feature reads as "not
    enabled" instead of "server broken".
    """
    import json

    if not get_settings().MCP_JWT_PRIVATE_KEY_PEM:
        return Response(
            content=json.dumps(
                {"detail": "MCP token signing is not configured on this deployment."}
            ),
            status_code=503,
            media_type="application/json",
        )

    body = json.dumps(public_jwks())
    return Response(
        content=body,
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=600"},
    )
