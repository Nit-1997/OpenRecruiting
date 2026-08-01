"""POST /api/v2/internal/cortex/service-token — mint a per-org Cortex MCP token.

Machine-to-machine endpoint. The intake context-builder Lambda authenticates
with X-Internal-Secret and asks for a token scoped to a specific org. The org
binding comes from the signed JWT we mint here, NOT from anything the Lambda
later sends to Cortex — so a caller cannot read another tenant's graph.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.v2.core.dependencies import get_supabase, verify_internal_secret
from app.services.mcp.token_minter import mint_cortex_service_token

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/internal/cortex",
    tags=["v2/internal-cortex"],
    dependencies=[Depends(verify_internal_secret)],
)


class ServiceTokenRequest(BaseModel):
    organization_id: str


class ServiceTokenResponse(BaseModel):
    token: str
    expires_in: int


@router.post("/service-token", response_model=ServiceTokenResponse)
async def mint_service_token(
    body: ServiceTokenRequest,
    supabase=Depends(get_supabase),
):
    org = (
        await supabase.table("organizations")
        .select("id,name")
        .eq("id", body.organization_id)
        .single()
        .execute_async()
    ).data
    if not org:
        return JSONResponse(status_code=404, content={"detail": "Organization not found"})

    token, expires_in = mint_cortex_service_token(
        org_id=str(org["id"]),
        org_name=org.get("name") or "",
    )
    logger.info("cortex_service_token_minted", org_id=str(org["id"]), expires_in=expires_in)
    return ServiceTokenResponse(token=token, expires_in=expires_in)
